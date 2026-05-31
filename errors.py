#errors.py
class BusinessError(Exception):
    """飞书业务级失败，返回给 LLM 处理，不缓存成功"""
    pass
class FatalError(Exception):
    """llm修不好只能返回给人工"""
    pass