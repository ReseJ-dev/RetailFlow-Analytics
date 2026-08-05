from dataclasses import dataclass

import pandas as pd
from app.pages.upload_data import _read_uploaded_source, _same_upload
from app.state import AppPage, StateKey
from streamlit.testing.v1 import AppTest

from retailflow.common.exceptions import DataSourceError
from retailflow.ingestion.models import FileMetadata, LoadedDataset


@dataclass(frozen=True)
class FakeUpload:
    name: str
    content: bytes
    file_id: str | None = None

    @property
    def size(self) -> int:
        return len(self.content)

    def getvalue(self) -> bytes:
        return self.content


def _loaded_dataset(filename: str, size: int) -> LoadedDataset:
    return LoadedDataset(
        dataframe=pd.DataFrame({"id": [1]}),
        metadata=FileMetadata(
            filename=filename,
            file_type="csv",
            file_size=size,
            row_count=1,
            column_count=1,
            columns=("id",),
        ),
    )


def _open_upload_page() -> AppTest:
    app = AppTest.from_file("app/main.py", default_timeout=10).run()
    upload_navigation = next(
        button for button in app.sidebar.button if button.label == AppPage.UPLOAD_DATA.value
    )
    return upload_navigation.click().run()


def test_file_mode_shows_required_optional_and_disabled_readiness() -> None:
    app = _open_upload_page()

    assert not app.exception
    assert [uploader.label for uploader in app.file_uploader] == [
        "Select Orders",
        "Select Products",
        "Select Inventory",
        "Select Returns",
        "Select Monthly Targets",
    ]
    assert app.segmented_control[0].options == ["Files", "REST API"]
    validate = next(button for button in app.button if button.label == "Validate Data")
    assert validate.disabled
    assert any(
        "Still required: Orders, Products, Inventory, Returns" in markdown.value
        for markdown in app.markdown
    )


def test_mixed_mode_is_only_shown_when_configuration_enables_it(monkeypatch) -> None:
    monkeypatch.setenv("RETAILFLOW_SOURCES__ALLOW_MIXED_SOURCES", "true")

    app = _open_upload_page()

    assert not app.exception
    assert app.segmented_control[0].options == ["Files", "REST API", "Mixed"]


def test_selected_files_survive_rerun_and_validate_into_existing_workflow() -> None:
    app = _open_upload_page()
    sources = (
        (
            "orders.csv",
            b"order_id,order_date,product_id,quantity,unit_price\nO-1,2026-01-01,P-1,1,10\n",
        ),
        ("products.csv", b"product_id,product_name,purchase_cost\nP-1,Product,5\n"),
        (
            "inventory.csv",
            b"product_id,warehouse,stock_quantity,reserved_quantity,reorder_level,last_restock_date\nP-1,A,5,0,2,2026-01-01\n",
        ),
        ("returns.csv", b"return_id,order_id,product_id,return_date,quantity,refund_amount\n"),
    )
    for uploader, (filename, content) in zip(app.file_uploader[:4], sources, strict=True):
        uploader.upload(filename, content, "text/csv")

    app = app.run()
    assert not app.exception
    assert [uploader.value.name for uploader in app.file_uploader[:4]] == [
        source[0] for source in sources
    ]
    app = app.run()
    assert [uploader.value.name for uploader in app.file_uploader[:4]] == [
        source[0] for source in sources
    ]
    validate = next(button for button in app.button if button.label == "Validate Data")
    assert not validate.disabled

    app = validate.click().run()

    assert not app.exception
    assert app.title[0].value == AppPage.DATA_QUALITY.value
    loaded = app.session_state[StateKey.LOADED_DATASETS.value]
    assert set(loaded) == {"orders", "products", "inventory", "returns"}
    assert app.session_state[StateKey.COLUMN_MAPPINGS.value] == {}


def test_rest_api_mode_masks_token_and_shows_endpoint_statuses() -> None:
    app = _open_upload_page()

    app = app.segmented_control[0].select("REST API").run()

    assert not app.exception
    assert not app.file_uploader
    token = next(item for item in app.text_input if item.label == "Bearer Token")
    assert token.proto.type == 1
    assert [caption.value for caption in app.caption].count("Endpoint: /api/orders") == 1
    assert any(button.label == "Test Connection" for button in app.button)
    assert any(button.label == "Load Data" for button in app.button)

    app = token.input("temporary-demo-secret").run()

    visible_copy = [item.value for item in (*app.markdown, *app.caption)]
    assert not any("temporary-demo-secret" in value for value in visible_copy)
    assert "api_token" not in app.session_state[StateKey.IMPORT_SETTINGS.value]


def test_reset_sources_clears_staged_uploads() -> None:
    app = _open_upload_page()
    app.file_uploader[0].upload("orders.csv", b"order_id\nO-1\n", "text/csv")
    app = app.run()
    reset = next(button for button in app.button if button.label == "Reset Sources")
    assert not reset.disabled

    app = reset.click().run()

    assert not app.exception
    assert all(uploader.value is None for uploader in app.file_uploader)
    assert app.session_state[StateKey.LOADED_DATASETS.value] == {}


def test_unchanged_upload_matches_loaded_metadata_without_reading_bytes() -> None:
    upload = FakeUpload("orders.csv", b"1234", "upload-one")

    assert _same_upload(upload, _loaded_dataset("orders.csv", 4))
    assert _same_upload(
        upload,
        _loaded_dataset("orders.csv", 4),
        loaded_file_id="upload-one",
    )
    assert not _same_upload(
        upload,
        _loaded_dataset("orders.csv", 4),
        loaded_file_id="replacement-upload",
    )
    assert not _same_upload(upload, _loaded_dataset("orders.csv", 5))


def test_file_reader_preserves_actionable_error_without_technical_details(monkeypatch) -> None:
    session: dict[str, object] = {}
    monkeypatch.setattr("app.pages.upload_data.st.session_state", session)

    def reject_file(*args, **kwargs) -> LoadedDataset:
        del args, kwargs
        raise DataSourceError("The CSV file could not be decoded. Try another encoding.")

    result = _read_uploaded_source(
        "orders",
        FakeUpload("orders.csv", b"invalid"),
        loader=reject_file,
    )

    assert result is None
    assert session["_source_error_orders"] == (
        "The CSV file could not be decoded. Try another encoding."
    )
