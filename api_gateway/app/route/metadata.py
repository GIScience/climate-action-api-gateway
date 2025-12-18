from dataclasses import dataclass

from climatoology.base.plugin_info import Concern
from fastapi import APIRouter

router = APIRouter(prefix='/metadata', tags=['metadata'])


@dataclass
class Concerns:
    items: set[str]


@router.get(
    path='/concerns',
    summary='Retrieve a list of concerns.',
    description='Concerns are tag-like descriptions of plugin topics.',
)
def get_concerns() -> Concerns:
    return Concerns(items={c.value for c in Concern})
