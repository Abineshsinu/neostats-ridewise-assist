from src.city import normalize_city


def test_all_four_bengaluru_variants_normalize_to_the_same_value():
    variants = ["Bengaluru", "Bangalore", "BLR", "bangalore "]
    normalized = {normalize_city(v) for v in variants}
    assert normalized == {"Bengaluru"}


def test_blr_case_insensitive():
    assert normalize_city("blr") == "Bengaluru"
    assert normalize_city("Blr") == "Bengaluru"


def test_strips_whitespace():
    assert normalize_city("  Bengaluru  ") == "Bengaluru"


def test_other_cities_are_tidied_not_changed_to_bengaluru():
    assert normalize_city("Hyderabad") == "Hyderabad"
    assert normalize_city("chennai") == "Chennai"
    assert normalize_city("  pune ") == "Pune"


def test_none_passes_through():
    assert normalize_city(None) is None
