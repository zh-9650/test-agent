import json
from pydantic import BaseModel, Field
from core.llm_client import get_llm_client

class SystemModel(BaseModel):
    """Structured representation of the system derived from documents."""
    modules: list[str] = Field(default_factory=list, description="Core system modules (e.g., 'Order Management', 'User System')")
    roles: list[str] = Field(default_factory=list, description="User roles identified in the system (e.g., 'Admin', 'Applicant')")
    business_flows: list[str] = Field(default_factory=list, description="Key business processes/flows (e.g., 'Create Order', 'Approve Order')")
    states: list[str] = Field(default_factory=list, description="Possible entity states in the system (e.g., 'Draft', 'Pending Approval', 'Approved')")


async def generate_system_model(prd_content: str, api_doc_content: str, changelog_content: str) -> SystemModel:
    """
    Extract a structured SystemModel from available documentation.
    This acts as the 'System Modeling Agent' mapping docs to cognitive system knowledge.
    """
    llm = get_llm_client("default")
    
    prompt = f"""
你是一位高级系统架构师和资深测试专家。
请根据提供的系统文档，深入理解目标系统，并提炼出系统的核心认知模型。

你需要提取以下信息：
1. modules: 系统包含的核心功能模块（如：订单管理、用户系统等）
2. roles: 系统中出现的不同用户角色（如：申请人、审批人、普通用户等）
3. business_flows: 系统的关键业务流/动作操作（如：创建订单、审批通过、驳回审批等）
4. states: 核心业务实体可能存在的状态流转（如：草稿、待审批、已完成等）

如果文档缺乏某项信息，请基于常识或已提供的有限信息进行合理推断，但不要无中生有。

### 产品需求文档 (PRD)
{prd_content or "未提供"}

### 接口文档 / Swagger
{api_doc_content or "未提供"}

### 变更日志 (Changelog)
{changelog_content or "未提供"}

请以 JSON 格式返回你的分析结果，结构必须严格遵循要求。
"""
    
    llm_with_struct = llm.with_structured_output(SystemModel)
    
    try:
        result = await llm_with_struct.ainvoke(prompt)
        if result is None:
            print("[SystemModeler] LLM returned None, falling back to empty model")
            return SystemModel()
        return result
    except Exception as e:
        print(f"[SystemModeler] Error extracting system model: {e}")
        return SystemModel()
