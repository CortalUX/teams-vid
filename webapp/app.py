""" Server allows people to record themselves on the fly,
and sync with their teams, wherever they may be."""
import uuid
import os
from azure.storage.blob import ContentSettings
from azure.storage.blob.aio import BlobClient, BlobServiceClient
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles
from starlette.routing import Route, Mount
from starlette.templating import Jinja2Templates
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
import aiofiles  # pylint: disable=W0611
import multipart  # pylint: disable=W0611
from dotenv import load_dotenv
from asgi_auth_github import GitHubAuth
import uvicorn
from . import video_indexer

templates = Jinja2Templates(directory="templates")
load_dotenv()


async def homepage(request):
    """Renders the default homepage."""
    await request.send_push_promise("/static/custom.min.css")
    await request.send_push_promise("/static/css/bootstrap.min.css")
    await request.send_push_promise("/favicon.ico")
    return templates.TemplateResponse("index.html", {"request": request})


async def gallery(request):
    """Renders the gallery view from uploaded blob storage."""
    blob_service_client = BlobServiceClient(
        account_url=f"https://{os.getenv('AZURE_STORAGE_ACCOUNT')}.blob.core.windows.net/",
        credential=os.getenv("AZURE_STORAGE_KEY"),
    )
    container_client = blob_service_client.get_container_client(
        os.getenv("AZURE_STORAGE_VIDEO_CONTAINER")
    )
    blobs_list = []
    async for blob in container_client.list_blobs(  # pylint: disable=E1133
        include=["metadata"]
    ):
        metadata = blob.metadata
        blobs_list.append(
            {
                "uuid": metadata["uuid"],
                "image_url": "https://bootsnipp.com/bootstrap-builder/libs/builder/icons/image.svg",
                "author": metadata["author"],
                "title": metadata["title"],
                "badge": metadata["badge"],
            }
        )
    await container_client.close()
    await blob_service_client.close()
    return templates.TemplateResponse(
        "gallery.html", {"request": request, "blobs": blobs_list}
    )


async def record(request):
    """Renders the video recording and upload view."""
    return templates.TemplateResponse("record.html", {"request": request})


async def play(request):
    """Renders the video player view."""
    return templates.TemplateResponse("play.html", {"request": request})


async def about(request):
    """Renders the About page."""
    return templates.TemplateResponse("about.html", {"request": request})


async def add_file_and_metadata_to_blob_storage(
    file_name, file_contents, file_content_type
):
    """Adds uploaded files to blob storage with metadata."""
    extension = file_name.split(".")[-1].lower()
    file_uuid_str = str(uuid.uuid4())
    new_filename = f"{file_uuid_str}.{extension}"
    blob = BlobClient(
        account_url=f"https://{os.getenv('AZURE_STORAGE_ACCOUNT')}.blob.core.windows.net/",
        credential=os.getenv("AZURE_STORAGE_KEY"),
        container_name=os.getenv("AZURE_STORAGE_VIDEO_CONTAINER"),
        blob_name=new_filename,
    )

    await blob.upload_blob(
        file_contents,
        metadata={
            "original_file_name": file_name,
            "uuid": file_uuid_str,
            "author": "Dummy User",
            "title": "Dummy title",
            "badge": "dummy badge",
        },
        content_settings=ContentSettings(content_type=file_content_type),
    )
    await blob.close()


async def upload_completed(request):
    """Renders the file completed upload page."""
    form = await request.form()
    video_recording = form["video_recording"]
    filename = video_recording.filename
    content_type = video_recording.content_type
    contents = await video_recording.read()
    await add_file_and_metadata_to_blob_storage(filename, contents, content_type)
    return templates.TemplateResponse("uploaded.html", {"request": request})


async def github_debug(request):
    """Return the output from logged in GitHub users."""
    # TODO: Remove from the final application
    return JSONResponse({"auth": request.scope["auth"]})


async def startup_get_video_indexer_token():
    video_indexer_key = os.getenv("VIDEO_INDEXER_PRIMARY_KEY")
    assert video_indexer_key is not None


async def error_template(request, exc):
    """Returns an error template and a message specific to the error case."""
    error_messages = {
        404: "Sorry, the page you're looking for isn't here.",
        500: "Server error.",
    }
    if exc.status_code in error_messages:
        error_message = error_messages[exc.status_code]
    else:
        error_message = "No message saved for this error."
    return templates.TemplateResponse(
        "layout/error.html",
        {
            "request": request,
            "error_code": exc.status_code,
            "error_message": error_message,
        },
    )


routes = [
    Route("/", homepage),
    Route("/gallery", gallery),
    Route("/file_upload", upload_completed, methods=["POST"]),
    Route("/record", record),
    Route("/play", play),
    Route("/about", about),
    Route("/favicon.ico", FileResponse("static/favicon.ico")),
    Route("/ghdebug", github_debug),
    Mount(
        "/static",
        app=StaticFiles(directory="static", packages=["bootstrap4"]),
        name="static",
    ),
]

middleware = [
    Middleware(GZipMiddleware, minimum_size=500),
    Middleware(
        uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware, trusted_hosts="*"
    ),
]

exception_handlers = {404: error_template, 500: error_template}

if os.getenv("DEBUG", None) is None:
    middleware.append(
        Middleware(
            GitHubAuth,
            client_id=os.getenv("GITHUB_CLIENT_ID"),
            client_secret=os.getenv("GITHUB_CLIENT_SECRET"),
            require_auth=True,
            allow_users=os.getenv("GITHUB_ALLOWED_USERS").split(","),
        ),  # FIXME: Figure out why team authentication isn't working
    )

app = Starlette(
    debug=True,
    routes=routes,
    middleware=middleware,
    exception_handlers=exception_handlers,
    on_startup=[startup_get_video_indexer_token],
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", log_level="info")
