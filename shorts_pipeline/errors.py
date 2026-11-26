class PipelineError(RuntimeError):
    """어느 단계(step)에서 실패했는지 함께 담는 파이프라인 오류."""

    def __init__(self, step: str, message: str, *, scene: int | None = None):
        self.step = step
        self.scene = scene
        where = f"[{step}]" + (f"[scene {scene}]" if scene is not None else "")
        super().__init__(f"{where} {message}")


class AssetGenerationError(PipelineError):
    """Higgsfield 생성 실패(failed/nsfw/canceled 또는 타임아웃)."""
