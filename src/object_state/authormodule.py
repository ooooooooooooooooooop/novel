"""AuthorModule — 作者模块：一个壳，两层（作者性方案 §2）.

风格库升级为作者模块：文风直接并入作者模块，作为作者的总载体。
但「并入」≠「合并成一个对象」（禁止 7）：两层同住一个模块、共享同一套
存储与检索，但字段不混、仍是两个可独立存在/独立为空的子层。

    AuthorModule（作者模块，住 style_library/）
    ├── 文风层 style: StyleProfile    = 这个作者【怎么写】
    └── 选择层 kernel: Optional[AuthorKernel] = None = 这个作者【为什么这样选】

获取方式不同：文风层一次提炼就有；选择层必须从长期行为里慢慢长。
生命周期不同：文风可以空着选择层先生成；选择层没攒够前，文风层照常工作。
语义不同（禁止 7）：Style 回答「怎么写」，Author 回答「为什么这样选」。

kernel 为空时零成本：不渲染、不注入、字节不变，等价于现状的纯风格档案；
kernel 长出来后挂进同一个档案。

隐私：kernel 含作品语境（supporting_choices 引作品内 decision_id），
存本地 gitignored 的 sidecar（`output_dir/author_kernel.json`）；风格库只放中性
方法论（style）。存储实现见 `src/workflow_action/authormemory.py`
（save_author_kernel / load_author_kernel）。
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.object_state.authorkernel import AuthorKernel
from src.object_state.styleprofile import StyleProfile


class AuthorModule(BaseModel):
    """作者模块壳：文风层（现有 StyleProfile）+ 选择层（Optional AuthorKernel）.

    两个子层独立存在/独立为空。kernel=None 时退化为纯风格档案（零成本）。
    """

    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(description="作者模块标识（即风格档案 id）")
    schema_version: int = Field(default=1, ge=1)
    style: Optional[StyleProfile] = Field(
        default=None, description="文风层：怎么写（现有 StyleProfile，可为空）"
    )
    kernel: Optional[AuthorKernel] = Field(
        default=None, description="选择层：为什么这样选（未长成前 None）"
    )

    @property
    def has_kernel(self) -> bool:
        return self.kernel is not None and self.kernel.status != "empty"
