from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api_routes import router
from .ota import get_package
from .ota import router as ota_router


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except (HTTPException, StarletteHTTPException) as ex:
            if ex.status_code == 404:
                return await super().get_response("index.html", scope)
            else:
                raise ex


def get_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        get_package()  # Verify signed assets before accepting requests.
        yield

    app = FastAPI(openapi_url=None, lifespan=lifespan)

    @app.get("/healthz")
    def kubernetes_liveness_probe():
        return {"status": "healthy"}

    @app.get("/metrics")
    def metrics():
        """Endpoint to expose Prometheus metrics."""
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(router)
    app.include_router(ota_router)
    app.mount(
        "/", SPAStaticFiles(directory="./frontend/dist", html=True), name="static"
    )

    return app


app = get_app()
