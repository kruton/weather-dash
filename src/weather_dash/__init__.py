from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from .api_routes import router
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST


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
    app = FastAPI(openapi_url=None)

    @app.get("/healthz")
    def kubernetes_liveness_probe():
        return {"status": "healthy"}

    @app.get("/metrics")
    def metrics():
        """Endpoint to expose Prometheus metrics."""
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(router)
    app.mount(
        "/", SPAStaticFiles(directory="./frontend/dist", html=True), name="static"
    )

    return app


app = get_app()
