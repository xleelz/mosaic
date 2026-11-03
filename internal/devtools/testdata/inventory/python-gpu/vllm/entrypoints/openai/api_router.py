from fastapi import APIRouter, FastAPI

router = APIRouter()

# @router.get("/commented")
NOTE = '@router.get("/in-string")'


@router.post("/v1/chat/completions", dependencies=[])
async def create_chat_completion(request, raw_request):
    return None


@router.get("/health", response_class=Response)
async def health(raw_request):
    return None


@router.api_route("/ping", methods=["GET", "POST"])
async def ping():
    return None


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_api_route("/abort", abort_requests, methods=["POST"])
    for route in routes:
        app.add_api_route(route.path, disabled, methods=["POST"])
    return app
