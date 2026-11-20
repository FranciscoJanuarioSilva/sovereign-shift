from sovereign_shift import paths


def test_repo_copy_first_then_the_bundled_copy(tmp_path, monkeypatch):
    assert paths.data_path("data/leaseweb_catalog.json") == paths.REPO / "data" / "leaseweb_catalog.json"
    # an installed wheel has no repo around it, so the bundled copy is used
    monkeypatch.setattr(paths, "REPO", tmp_path / "nowhere")
    assert paths.data_path("mappings/regions.yaml") == paths.BUNDLED / "mappings" / "regions.yaml"
