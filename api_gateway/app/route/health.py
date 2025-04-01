from fastapi import APIRouter

router = APIRouter(prefix='/health')


@router.get(path='/', status_code=200, summary='Hey, is this thing on?')
def is_ok() -> dict:
    return {'status': 'ok'}
