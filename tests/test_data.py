from claimguard.data import load_dfs, load_imr, load_imr_findings, load_ncd, manifest, request_text, verify_snapshot


def test_snapshot_checksums_match_manifest():
    v = verify_snapshot()
    assert v["ok"], v["mismatched"]
    assert v["files"] == 4


def test_counts_are_the_real_public_files():
    c = manifest()["counts"]
    assert c["imr_rows"] == 42710 and c["imr_overturned"] == 22431 and c["imr_upheld"] == 20279
    assert c["dfs_rows"] == 62249 and c["ncd_current"] == 345
    src = manifest()["sources"]
    assert src["ca_dmhc_imr"]["bytes"] == 85409358
    raw_rows = {s["dataset"]: s["rows_in"] for s in manifest()["cleaning_log"] if s["step"].startswith("read")}
    assert raw_rows["ca_dmhc_imr"] == 42749 and raw_rows["ny_dfs_external_appeals"] == 63499 and raw_rows["cms_ncd"] == 357


def test_slim_table_has_no_findings_and_unique_ids():
    imr = load_imr()
    assert "Findings" not in imr.columns and imr.ReferenceID.is_unique
    assert set(imr.overturned.unique()) == {0, 1}
    assert load_dfs().case_number.is_unique
    assert len(load_imr_findings()) == 8229
    assert load_ncd().ncd_id.is_unique


def test_request_text_is_pre_decision():
    f = ("Findings: The physician reviewer found that a patient has requested authorization and coverage for Omnitrope. "
         "Therefore, the requested Omnitrope is medically necessary.")
    assert request_text(f) == "authorization and coverage for Omnitrope"
    assert "necessary" not in request_text(f)
