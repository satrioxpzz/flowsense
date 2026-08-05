from flowsense.density import classify_density, density_from_count

def test_density_from_count_thresholds():
    assert density_from_count(0) == "lancar"
    assert density_from_count(3) == "lancar"
    assert density_from_count(4) == "sedang"
    assert density_from_count(8) == "sedang"
    assert density_from_count(9) == "padat"

def test_classify_density_per_lane():
    per_lane = {"kota": 2, "ploso": 5, "demak": 12}
    assert classify_density(per_lane) == {
        "kota": "lancar",
        "ploso": "sedang",
        "demak": "padat",
    }

def test_classify_density_zero_is_lancar():
    assert classify_density({"kota": 0, "ploso": 0}) == {"kota": "lancar", "ploso": "lancar"}

def test_classify_density_custom_thresholds():
    assert classify_density({"kota": 10}, thresholds=(5, 15)) == {"kota": "sedang"}
