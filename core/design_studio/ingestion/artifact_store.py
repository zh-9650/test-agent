"""内容寻址的本地原始资料仓库。"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from core.design_studio.contracts import SourceInput

from .inspection import inspect_source, sanitize_origin_uri


class FilesystemArtifactStore:
    """在解析前冻结原件，避免 locator 指向后来被覆盖的文件。

    仓库布局为 ``<root>/raw/<sha256>/<名称hash>/payload/<原文件或目录>``。
    相同内容和名称复用 payload，但不同 ``source_id`` 仍由上层合同分别保存身份。
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def capture(self, source: SourceInput) -> SourceInput:
        original_path = source.path.resolve()
        if original_path.is_dir():
            try:
                self.root.relative_to(original_path)
            except ValueError:
                pass
            else:
                raise ValueError("artifact_root 不能位于待冻结的资料目录内部")
        self._reject_secret_paths(original_path)
        original_artifact = inspect_source(source)
        digest = original_artifact.sha256
        payload_name = original_path.name
        name_key = sha256(payload_name.encode("utf-8")).hexdigest()[:16].upper()
        target = self.root / "raw" / digest / name_key
        captured_path = target / "payload" / payload_name

        if target.exists():
            self._validate_existing(target, digest, captured_path)
            captured_input = self._captured_input(
                source,
                captured_path,
                original_path,
                digest,
            )
            self._verify_payload(captured_input, digest)
            self._write_identity_manifest(
                target,
                captured_input,
                captured_path,
            )
            return captured_input

        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / f".capture-{uuid4().hex}"
        payload_root = staging / "payload"
        payload_root.mkdir(parents=True)
        staged_path = payload_root / payload_name
        try:
            if original_path.is_dir():
                self._reject_symlinks(original_path)
                shutil.copytree(original_path, staged_path)
            else:
                if source.path.is_symlink():
                    raise ValueError("原始资料路径不能是符号链接")
                shutil.copy2(original_path, staged_path)

            captured_source = self._captured_input(
                source,
                staged_path,
                original_path,
                digest,
            )
            captured_artifact = inspect_source(captured_source)
            if captured_artifact.sha256 != digest:
                raise ValueError("资料在冻结期间发生变化，已拒绝不一致快照")

            manifest = {
                "schema_version": "source_capture_manifest.v1",
                "sha256": digest,
                "byte_size": captured_artifact.byte_size,
                "original_name": source.original_name or original_path.name,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "payload": f"payload/{payload_name}",
            }
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(staging, target)
            except OSError:
                if not target.exists():
                    raise
                shutil.rmtree(staging)
            self._validate_existing(target, digest, captured_path)
            captured_input = self._captured_input(
                source,
                captured_path,
                original_path,
                digest,
            )
            self._verify_payload(captured_input, digest)
            self._write_identity_manifest(
                target,
                captured_input,
                captured_path,
            )
            return captured_input
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    @staticmethod
    def _reject_symlinks(root: Path) -> None:
        symlinks = [item for item in root.rglob("*") if item.is_symlink()]
        if symlinks:
            relative = symlinks[0].relative_to(root).as_posix()
            raise ValueError(f"资料目录包含符号链接: {relative}")

    @staticmethod
    def _reject_secret_paths(path: Path) -> None:
        safe_env_templates = {
            ".env.example",
            ".env.sample",
            ".env.template",
        }

        def is_secret(candidate: Path) -> bool:
            name = candidate.name.casefold()
            if name in safe_env_templates:
                return False
            if name == ".env" or name.startswith(".env."):
                return True
            if name in {
                ".npmrc",
                ".pypirc",
                "credentials.json",
                "id_dsa",
                "id_ed25519",
                "id_rsa",
                "secrets.json",
                "secrets.yaml",
                "secrets.yml",
            }:
                return True
            return candidate.suffix.casefold() in {".key", ".p12", ".pfx"}

        candidates = (
            [item for item in path.rglob("*") if item.is_file()]
            if path.is_dir()
            else [path]
        )
        secret_paths = [candidate for candidate in candidates if is_secret(candidate)]
        if secret_paths:
            candidate = secret_paths[0]
            display = (
                candidate.relative_to(path).as_posix()
                if path.is_dir()
                else candidate.name
            )
            raise ValueError(
                f"原始资料包含疑似 Secret 文件，必须改用 secret_refs: {display}"
            )

    @staticmethod
    def _captured_input(
        source: SourceInput,
        captured_path: Path,
        original_path: Path,
        digest: str,
    ) -> SourceInput:
        return source.model_copy(
            update={
                "path": captured_path,
                "origin_uri": sanitize_origin_uri(
                    source.origin_uri or str(original_path)
                ),
                "original_name": source.original_name or original_path.name,
                "source_version": source.source_version or digest,
            }
        )

    @staticmethod
    def _validate_existing(
        target: Path,
        expected_hash: str,
        captured_path: Path,
    ) -> None:
        manifest_path = target / "manifest.json"
        if not manifest_path.is_file() or not captured_path.exists():
            raise ValueError(f"原始资料仓库存在不完整快照: {target}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("sha256") != expected_hash:
            raise ValueError(f"原始资料仓库 hash 冲突: {target}")

    @staticmethod
    def _verify_payload(source: SourceInput, expected_hash: str) -> None:
        actual = inspect_source(source).sha256
        if actual != expected_hash:
            raise ValueError(
                f"原始资料仓库 payload 校验失败: expected={expected_hash}, actual={actual}"
            )

    @staticmethod
    def _write_identity_manifest(
        target: Path,
        source: SourceInput,
        captured_path: Path,
    ) -> None:
        identity = {
            "source_id": source.source_id,
            "source_kind": source.source_kind,
            "authority": source.authority.value,
            "required": source.required,
            "source_version": source.source_version,
            "original_name": source.original_name,
            "origin_uri": sanitize_origin_uri(source.origin_uri),
            "payload": captured_path.relative_to(target).as_posix(),
        }
        serialized_identity = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        identity_key = (
            sha256(serialized_identity.encode("utf-8"))
            .hexdigest()[:32]
            .upper()
        )
        identity_dir = target / "identities"
        identity_dir.mkdir(parents=True, exist_ok=True)
        identity_path = identity_dir / f"{identity_key}.json"
        if identity_path.exists():
            return
        payload = {
            "schema_version": "source_identity_manifest.v1",
            **identity,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary = identity_dir / f".{identity_key}.{uuid4().hex[:8]}.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            os.replace(temporary, identity_path)
        finally:
            if temporary.exists():
                temporary.unlink()
