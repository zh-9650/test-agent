"""PNG/JPEG 二进制与元数据解析器。"""

from __future__ import annotations

from PIL import Image, UnidentifiedImageError

from core.design_studio.contracts import ParsedArtifact, SourceArtifact, SourceInput

from .base import finalize_artifact, finding, make_block


class ImageParser:
    parser_name = "raster_image_metadata"
    parser_version = "1.0.0"

    def supports(self, source: SourceInput, artifact: SourceArtifact) -> bool:
        del artifact
        return source.path.suffix.casefold() in {".png", ".jpg", ".jpeg"}

    def parse(
        self,
        source: SourceInput,
        artifact: SourceArtifact,
    ) -> ParsedArtifact:
        try:
            with Image.open(source.path) as image:
                image.load()
                width, height = image.size
                image_format = image.format or source.path.suffix.lstrip(".").upper()
                mode = image.mode
                frame_count = getattr(image, "n_frames", 1)
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            return finalize_artifact(
                artifact=artifact,
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                blocks=[],
                detected_inventory={},
                parsed_inventory={},
                errors=[
                    finding(
                        "input.image_corrupt",
                        f"{type(exc).__name__}: {exc}",
                        artifact.original_name,
                    )
                ],
            )

        blocks = [
            make_block(
                artifact,
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                block_type="image",
                locator="image::metadata",
                order=1,
                structured_content={
                    "format": image_format,
                    "width": width,
                    "height": height,
                    "mode": mode,
                    "frame_count": frame_count,
                    "byte_size": artifact.byte_size,
                },
                asset_refs=[artifact.source_id],
            )
        ]
        inventory = {"images": 1, "ocr_blocks": 0, "visual_regions": 0}
        return finalize_artifact(
            artifact=artifact,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            blocks=blocks,
            detected_inventory=inventory,
            parsed_inventory=dict(inventory),
            unsupported_features=[
                finding(
                    "input.ocr_unavailable",
                    "当前适配器未生成 OCR 文本块。",
                    "image::metadata",
                ),
                finding(
                    "input.visual_semantics_unavailable",
                    "当前适配器未生成可验证的视觉区域和业务语义。",
                    "image::metadata",
                ),
            ],
        )
