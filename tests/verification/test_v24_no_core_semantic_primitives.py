from pathlib import Path


def test_v24_removes_fixed_surface_module_from_core():
    assert not Path("ai_core/utils/temporal_surface.py").exists()
    assert Path("ai_core/utils/semantic_surface.py").exists()


def test_v24_core_has_no_fixed_schedule_source_word_lists():
    blocked_literals = [
        "January", "February", "March", "April", "June", "July", "August",
        "September", "October", "November", "December",
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
        "日週月年時間分秒",
    ]
    offenders = []
    for path in Path("ai_core").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for literal in blocked_literals:
            if literal in text:
                offenders.append(f"{path}:{literal}")
    assert offenders == []


def test_v24_runtime_pack_generation_is_outside_core(tmp_path):
    from ai_core.utils.semantic_surface import RuntimeSemanticSurfaceNormalizer

    pack_dir = tmp_path / "runtime" / "generated" / "semantic_packs"
    normalizer = RuntimeSemanticSurfaceNormalizer(pack_dir=pack_dir)
    pack = normalizer.generate_runtime_pack(
        request_text="Prepare a 3-unit result for AlphaPlace.",
        values=["P3D"],
        pack_name="case_pack",
    )
    assert pack["entries"][0]["aliases"] == ["3-unit"]
    assert (pack_dir / "case_pack.json").exists()
