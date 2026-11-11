from datetime import date

from app.identifier import aggregate, birdnet_week, split_label


def test_split_label():
    assert split_label("Turdus migratorius_American Robin") == ("Turdus migratorius", "American Robin")
    assert split_label("Engine_Engine") == ("Engine", "Engine")


def test_birdnet_week_has_48_weeks():
    assert birdnet_week(date(2026, 1, 1)) == 1
    assert birdnet_week(date(2026, 1, 31)) == 4
    assert birdnet_week(date(2026, 11, 9)) == 42
    assert birdnet_week(date(2026, 12, 31)) == 48


def test_aggregate_keeps_best_chunk_per_species_and_drops_weak_scores():
    rows = [
        ("Turdus migratorius_American Robin", 0.6, 0.0, 3.0),
        ("Turdus migratorius_American Robin", 0.9, 3.0, 6.0),
        ("Turdus migratorius_American Robin", 0.4, 6.0, 9.0),
        ("Cardinalis cardinalis_Northern Cardinal", 0.7, 0.0, 3.0),
        ("Cyanocitta cristata_Blue Jay", 0.1, 0.0, 3.0),
        ("Engine_Engine", 0.5, 0.0, 3.0),
    ]
    result = aggregate(rows, min_confidence=0.25)
    assert [d.common_name for d in result] == ["American Robin", "Northern Cardinal", "Engine"]
    robin = result[0]
    assert (robin.confidence, robin.start_s, robin.end_s, robin.n_segments) == (0.9, 3.0, 6.0, 3)
    assert not robin.is_noise
    assert result[2].is_noise
