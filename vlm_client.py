# --- bytes 版：以繼承擴充，不修改原始類別 ---------------------
from io import BytesIO
from typing import Any, Literal, Sequence
from PIL import Image

from mineru_vl_utils import MinerUClient, MinerUClientHelper
from mineru_vl_utils.mineru_client import MinerUClientHelper
from mineru_vl_utils.vlm_client import SamplingParams
from mineru_vl_utils.structs import ContentBlock

class BytesAwareMinerUClientHelper(MinerUClientHelper):
    """在不修改原始 Helper 的前提下，透過繼承讓所有入口都能吃 bytes。"""

    @staticmethod
    def _to_pil(img_or_bytes: Image.Image | bytes | bytearray | memoryview) -> Image.Image:
        if isinstance(img_or_bytes, Image.Image):
            return img_or_bytes
        if isinstance(img_or_bytes, (bytes, bytearray, memoryview)):
            im = Image.open(BytesIO(img_or_bytes))
            return im.convert("RGB")
        raise TypeError(f"Unsupported image input type: {type(img_or_bytes)}")

    # ---- 覆寫：單張 ----
    def resize_by_need(self, image: Image.Image | bytes | bytearray | memoryview) -> Image.Image:
        image = self._to_pil(image)
        return super().resize_by_need(image)

    def prepare_for_layout(self, image: Image.Image | bytes | bytearray | memoryview) -> Image.Image | bytes:
        image = self._to_pil(image)
        return super().prepare_for_layout(image)

    def prepare_for_extract(
        self,
        image: Image.Image | bytes | bytearray | memoryview,
        blocks: list[ContentBlock],
    ) -> tuple[list[Image.Image | bytes], list[str], list[SamplingParams | None], list[int]]:
        image = self._to_pil(image)
        return super().prepare_for_extract(image, blocks)

    # ---- 覆寫：批次 ----
    def batch_prepare_for_layout(
        self,
        executor,
        images: list[Image.Image | bytes | bytearray | memoryview],
    ) -> list[Image.Image | bytes]:
        # 交給父類，但保證每張都是 PIL
        images = [self._to_pil(im) if not isinstance(im, Image.Image) else im for im in images]
        return super().batch_prepare_for_layout(executor, images)  # type: ignore[arg-type]

    def batch_prepare_for_extract(
        self,
        executor,
        images: list[Image.Image | bytes | bytearray | memoryview],
        blocks_list: list[list[ContentBlock]],
    ) -> list[tuple[list[Image.Image | bytes], list[str], list[SamplingParams | None], list[int]]]:
        images = [self._to_pil(im) if not isinstance(im, Image.Image) else im for im in images]
        return super().batch_prepare_for_extract(executor, images, blocks_list)  # type: ignore[arg-type]

    # ---- 覆寫：Async ----
    async def aio_prepare_for_layout(
        self,
        executor,
        image: Image.Image | bytes | bytearray | memoryview,
    ) -> Image.Image | bytes:
        image = self._to_pil(image)
        return await super().aio_prepare_for_layout(executor, image)

    async def aio_prepare_for_extract(
        self,
        executor,
        image: Image.Image | bytes | bytearray | memoryview,
        blocks: list[ContentBlock],
    ) -> tuple[list[Image.Image | bytes], list[str], list[SamplingParams | None], list[int]]:
        image = self._to_pil(image)
        return await super().aio_prepare_for_extract(executor, image, blocks)


class MinerUClientBytes(MinerUClient):
    """
    繼承原 MinerUClient，但把 helper 換成能吃 bytes 的 Helper。
    其他公開 API（layout_detect / two_step_extract / 批次 / async）不需要改，直接沿用。
    """
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        # 用父類建立時的設定來建 bytes-aware helper，確保行為一致
        self.helper = BytesAwareMinerUClientHelper(
            backend=self.backend,
            prompts=self.prompts,
            sampling_params=self.sampling_params,
            layout_image_size=self.helper.layout_image_size,
            min_image_edge=self.helper.min_image_edge,
            max_image_edge_ratio=self.helper.max_image_edge_ratio,
            handle_equation_block=self.helper.handle_equation_block,
            abandon_list=self.helper.abandon_list,
            abandon_paratext=self.helper.abandon_paratext,
            debug=self.helper.debug,
        )
