"""Prepare cached quality-analysis observations for localized charts.

This module maps precomputed summaries to chart geometry and escaped
presentation values without acquiring sources or recalculating metrics.
"""

# Numerical ranges use typographic dashes in displayed prose.
# ruff: file-ignore[ambiguous-unicode-character-string]

from __future__ import annotations

from collections import defaultdict
from ipaddress import ip_address
from math import floor, log, log10
from operator import itemgetter
from re import fullmatch
from urllib.parse import quote

from data.articles.authorship_store import (
    MAIN_MIN_CHARACTERS,
    MAIN_SHARE_THRESHOLD,
    SIGNIFICANT_SHARE_THRESHOLD,
    UTF8_MAX_BYTES_PER_CHARACTER,
)
from data.articles.quality_selection import quartiles
from shared.assessment_profiles import assessment_profile
from webservice.presentation import (
    Interface,
    display_title,
    grouped_number,
    title_url,
    utc_time,
)
from webservice.quality_authorship import grade_label, review_url

ARTICLE_PAGE_SIZE = 10
ARTICLE_PAGE_SIZES = (ARTICLE_PAGE_SIZE, 20, 50, 100)
_PROFILE = assessment_profile("zhwiki", "电子游戏")
_GRADES = tuple(
    label.code
    for label in _PROFILE.classes
    if label.code
    in {
        "FA",
        "FL",
        "A",
        "AL",
        "GA",
        "Bplus",
        "B",
        "BL",
        "C",
        "CL",
        "Start",
        "List",
        "Stub",
        "SL",
        "Unassessed",
    }
)
_IMPORTANCE = tuple(
    label.code
    for label in _PROFILE.importance
    if label.code not in {"NA", "Bottom"}
)
_GRADE_GROUPS = {
    label.code: label.article_group
    for label in _PROFILE.classes
    if label.code in _GRADES
}
_DISTRIBUTION_GRADES = tuple(
    label.code
    for group in (0, 1, 2)
    for label in _PROFILE.classes
    if label.code in _GRADES
    and (
        2
        if label.code == "Unassessed"
        else int(label.code != label.article_group)
    )
    == group
)
_FIRST_FILTER_YEAR = 2009
_PROSE_LENGTH_LINEAR = 25_000


def _assessment_color(code: str, dimension: str) -> str:
    """Use the page's shared gray for unassessed or unknown categories.

    Returns:
        A quality-page color without changing the shared wiki profile.
    """
    if (dimension, code) in {
        ("class", "Unassessed"),
        ("importance", "Unknown"),
    }:
        return "#72989c"
    return _PROFILE.color(code, dimension)


def _number(value: float | None) -> str:
    """Display a measured value without turning missing data into zero.

    Returns:
        A grouped whole number or the shared unknown marker.
    """
    return "—" if value is None else grouped_number(value, decimals=0)


def _kilobytes(value: int | None) -> str:
    """Format a known UTF-8 source size.

    Returns:
        A decimal kilobyte value to one decimal place, or unknown.
    """
    return "—" if value is None else grouped_number(value / 1000, decimals=1)


def _range(row: dict, prefix: str) -> str:
    """Format two saved percentile endpoints for a distribution.

    Returns:
        A bounded numerical interval or an unknown marker.
    """
    low, high = row.get(f"{prefix}_low"), row.get(f"{prefix}_high")
    return (
        "—"
        if low is None or high is None
        else (
            grouped_number(low, decimals=0)
            + "–"
            + grouped_number(high, decimals=0)
        )
    )


def _pie(
    rows: list[dict],
    dimension: str,
    total: int,
    interface: Interface,
) -> list[dict]:
    """Position saved categories and format their exact share labels.

    Returns:
        Sector geometry and accessible labels without regrouping data.
    """
    categories = []
    for row in rows:
        code = row["grade" if dimension == "class" else "importance"]
        if (dimension == "importance" and code not in _IMPORTANCE) or (
            dimension == "class" and code in {"A", "AL"} and row["pages"] == 0
        ):
            continue
        fraction = row["pages"] / max(total, 1)
        categories.append({
            **row,
            "label": grade_label(code, interface)
            if dimension == "class"
            else interface.text(f"assessment.{dimension}.{code}"),
            "color": _assessment_color(code, dimension),
            "series": _IMPORTANCE.index(code)
            if code in _IMPORTANCE
            else len(_IMPORTANCE),
            "count_label": _number(row["pages"]),
            "share_label": f"{fraction * 100:.1f}%",
        })
    return categories


def _years(data: dict, interface: Interface) -> dict:
    """Keep exact annual rows and legends beside Matplotlib charts.

    Returns:
        Annual table values and the selected nonempty legend categories.
    """
    years = [
        {
            **row,
            "count_label": _number(row["pages"]),
            "segments": [
                {
                    "grade": code,
                    "count": row.get("grades", {}).get(code, 0),
                    "color": _assessment_color(code, "class"),
                    "label": grade_label(code, interface),
                }
                for code in _GRADES
                if row.get("grades", {}).get(code, 0)
            ],
        }
        for row in sorted(data.get("years", []), key=itemgetter("year"))
    ]
    return {
        "years": years,
        "year_legend": [
            {
                "grade": code,
                "label": grade_label(code, interface),
                "color": _assessment_color(code, "class"),
            }
            for code in _GRADES
            if any(
                segment["grade"] == code
                for year in years
                for segment in year["segments"]
            )
        ],
    }


def prose_length_maximum(data: dict) -> float:
    """Share one scale across groups and filters using saved lengths.

    Returns:
        Catalog-wide observed maximum, at least the 25,000 linear limit.
    """
    selection = data.get("selection")
    values = (
        (
            item["value"]
            for cell in selection.get("cells", [])
            for item in cell.get("histogram", [])
            if item["count"] > 0
        )
        if selection is not None
        else (
            row["prose_characters"]
            for row in data.get("articles", [])
            if row.get("prose_characters") is not None
        )
    )
    return max(_PROSE_LENGTH_LINEAR, max(values, default=0))


def prose_length_position(characters: float, maximum: float) -> float:
    """Reserve 90% for 0-25,000 characters and compress the tail by log.

    The shared observed maximum closes the logarithmic tail at 100%.
    Zero or missing observations never change the fixed linear segment.

    Returns:
        SVG coordinate between zero and 1,000, inclusive.
    """
    if characters <= _PROSE_LENGTH_LINEAR:
        return max(0, characters / _PROSE_LENGTH_LINEAR * 900)
    if maximum <= _PROSE_LENGTH_LINEAR:
        return 900
    return min(
        1000,
        900
        + 100
        * log(characters / _PROSE_LENGTH_LINEAR)
        / log(maximum / _PROSE_LENGTH_LINEAR),
    )


def _lengths(
    data: dict,
    interface: Interface,
    maximum: float,
) -> list[dict]:
    """Position saved percentile intervals on a shared visual scale.

    Returns:
        Localized ranges on the shared linear and logarithmic scale.
    """
    selection = data.get("selection") or {}
    quartile_lookup = {
        (row["group"], row[row["group"]]): row
        for row in quartiles(
            selection.get("cells", []),
            [row["grade"] for row in data.get("grade_totals", [])],
            selection.get("last_year", 9999),
            include_density=True,
        )
    }
    visible = [
        row
        for row in data.get("lengths", [])
        if not (
            (
                row["group"] == "importance"
                and row["importance"] not in _IMPORTANCE
            )
            or (
                row["group"] == "grade"
                and row["grade"] in {"A", "AL"}
                and row["pages"] == 0
            )
        )
    ]
    lengths = []
    for row in visible:
        low, high = row.get("central_68_low"), row.get("central_68_high")
        median = row.get("median_characters")
        points = quartile_lookup.get(
            (row["group"], row["grade"] or row["importance"]),
            {},
        )
        lengths.append({
            **row,
            "density": points.get("density", row.get("density", [])),
            "label": grade_label(row["grade"], interface)
            if row["group"] == "grade"
            else interface.text(f"assessment.importance.{row['importance']}"),
            "median_label": _number(median),
            "range_68": _range(row, "central_68"),
            "range_95": _range(row, "central_95"),
            "low": round(prose_length_position(low or 0, maximum), 2),
            "width": round(
                prose_length_position(high or 0, maximum)
                - prose_length_position(low or 0, maximum),
                2,
            ),
            "median_x": round(prose_length_position(median or 0, maximum), 2),
            "mean": points.get("mean"),
            "mean_x": round(
                prose_length_position(points["mean"], maximum),
                2,
            )
            if points.get("mean") is not None
            else None,
            "marker_titles": {
                key: interface.text(
                    f"quality_analysis.violin_{key}",
                    value=_percentile_label(value),
                )
                for key, value in (
                    ("minimum", points.get("minimum")),
                    ("p25", points.get("p25")),
                    ("p50", median),
                    ("p75", points.get("p75")),
                    ("maximum", points.get("maximum")),
                    ("mean", points.get("mean")),
                )
            },
            "extrema": [
                {
                    "kind": kind,
                    "value": points[kind],
                    "x": round(
                        prose_length_position(points[kind], maximum),
                        2,
                    ),
                }
                for kind in ("minimum", "maximum")
                if points.get(kind) is not None
            ],
            "quartiles": [
                {
                    "percentile": percentile,
                    "value": points[f"p{percentile}"],
                    "x": round(
                        prose_length_position(
                            points[f"p{percentile}"],
                            maximum,
                        ),
                        2,
                    ),
                }
                for percentile in (25, 75)
                if points.get(f"p{percentile}") is not None
            ],
            "summary": interface.text(
                "quality_analysis.violin_summary",
                pages=_number(row.get("pages")),
                measured=_number(row.get("measured")),
                minimum=_percentile_label(points.get("minimum")),
                p25=_percentile_label(points.get("p25")),
                p50=_percentile_label(median),
                p75=_percentile_label(points.get("p75")),
                maximum=_percentile_label(points.get("maximum")),
            ),
            "color": _assessment_color(
                row["grade"] or row["importance"],
                "class" if row["group"] == "grade" else "importance",
            ),
        })
    return lengths


def _percentile_label(value: float | None) -> str:
    """Round lengths to two significant digits without decimal places.

    Returns:
        A grouped integer with half values rounded up, or unknown.
    """
    if value is None:
        return "—"
    if value == 0:
        return "0"
    step = 10 ** max(0, floor(log10(value)) - 1)
    return grouped_number(floor(value / step + 0.5) * step)


def _articles(data: dict, interface: Interface) -> list[dict]:
    """Localize complete saved rows and their exact revision links.

    Returns:
        Unfiltered article rows with missing observations preserved.
    """
    articles = []
    for row in data.get("articles", []):
        page_id = row["page_id"]
        date = row.get("listed_date")
        importance = row.get("importance") or "Unknown"
        authorship = _authorship(row, interface)
        contributors = _main_contributors(authorship, interface)
        articles.append({
            **row,
            "default_selected": bool(
                (
                    not date
                    or _FIRST_FILTER_YEAR
                    <= int(str(date)[:4])
                    <= (data.get("selection") or {}).get("last_year", 9999)
                )
                and (
                    row["grade"]
                    not in {
                        "B",
                        "BL",
                        "C",
                        "CL",
                        "Start",
                        "List",
                        "Stub",
                        "SL",
                        "Unassessed",
                    }
                    or data.get("all_grades")
                ),
            ),
            "title_label": display_title(
                row["title"].replace("_", " "),
                interface.locale,
            ),
            "url": title_url(row["title"]),
            "talk_url": title_url("Talk:" + row["title"]),
            "grade_label": grade_label(row["grade"], interface),
            "grade_color": _assessment_color(row["grade"], "class"),
            "grade_order": _GRADES.index(row["grade"]),
            "importance": importance,
            "importance_label": interface.text(
                f"assessment.importance.{importance}",
            ),
            "importance_color": _assessment_color(importance, "importance"),
            "importance_order": _IMPORTANCE.index(importance)
            if importance in _IMPORTANCE
            else len(_IMPORTANCE),
            "date_label": interface.date(date) if date else None,
            "review_url": review_url({
                "nomination_link": row.get("listed_review_link"),
                "title": row["title"],
            }),
            "characters_label": _number(row.get("prose_characters")),
            "contributors": contributors,
            "main_authors": [author["name"] for author in contributors],
            "main_author_labels": [author["label"] for author in contributors],
            "significant_authors": [
                author["name"] for author in authorship["editors"]
            ]
            if authorship["available"]
            else [],
            "authorship_popup_id": f"quality-article-{page_id}-authorship"
            if authorship["available"]
            else None,
            "authorship_popup_title": interface.text(
                "quality_analysis.authorship_details",
                title=display_title(
                    row["title"].replace("_", " "),
                    interface.locale,
                ),
            ),
            "authorship": authorship,
            "source_label": _kilobytes(row.get("source_bytes")),
            "source_url": _revision_url(row.get("article_revision_id")),
        })
    return articles


def _revision_url(value: object) -> str | None:
    """Link a retained positive revision without inventing a boundary.

    Returns:
        A Chinese Wikipedia oldid URL, or none without a known revision.
    """
    if type(value) is not int or value <= 0:
        return None
    return f"https://zh.wikipedia.org/w/index.php?oldid={value}"


def _authorship(row: dict, interface: Interface) -> dict:
    """Format saved attribution boundaries and qualifying contributors.

    Returns:
        Dialog labels preserving independently missing range endpoints.
    """
    source = row.get("authorship") or {
        "available": row.get("authorship_available"),
        "eligible_bytes": row.get("authorship_eligible_bytes"),
        "contributors": row.get("authorship_editors", []),
        **{
            f"range_{boundary}_{field}": row.get(
                f"authorship_{boundary}_{field}",
            )
            for boundary in ("start", "end")
            for field in ("revision", "timestamp")
        },
    }
    boundaries = {}
    for boundary in ("start", "end"):
        revision = source.get(f"range_{boundary}_revision")
        instant = source.get(f"range_{boundary}_timestamp")
        url = _revision_url(revision)
        label = str(revision)
        if instant:
            label += " · " + interface.date(str(instant)[:10])
        boundaries[f"range_{boundary}"] = (
            {
                "url": url,
                "label": label,
                "date": interface.date(str(instant)[:10]) if instant else None,
            }
            if url
            else None
        )
    return {
        **boundaries,
        "visualization_url": (
            "https://xtools.wmcloud.org/authorship/zh.wikipedia.org/"
            + quote(row["title"].replace(" ", "_"), safe="")
            + "/"
            + str(source["range_end_revision"])
            if _revision_url(source.get("range_end_revision"))
            else None
        ),
        "available": bool(source.get("available")),
        "eligible_bytes_label": _number(source.get("eligible_bytes")),
        "editors": [
            _editor(editor, interface)
            for editor in source.get("contributors", [])
            if editor.get("share", 0) >= SIGNIFICANT_SHARE_THRESHOLD
        ],
    }


def _editor(source: dict, interface: Interface) -> dict:
    """Link registered accounts and public IP contributions correctly.

    Returns:
        Escaped display values with no invented account for unknown IDs.
    """
    identity = source["editor"]
    name = source.get("name")
    url = title_url(f"User:{name}") if name else None
    if identity.startswith("0|"):
        name = identity[2:]
        try:
            ip_address(name)
        except ValueError:
            name, url = None, None
        else:
            url = title_url(f"Special:Contributions/{name}")
    characters = source.get("characters")
    raw_bytes = source.get("raw_bytes")
    character_floor = characters or 0
    if characters is None and raw_bytes is None:
        # Older exact scores can prove a lower bound, even for UTF-8.
        character_floor = (
            source.get("bytes") or 0
        ) // UTF8_MAX_BYTES_PER_CHARACTER
    return {
        "name": name
        or interface.text("quality_analysis.unknown_editor", editor=identity),
        "url": url,
        "anonymous": identity.startswith("0|"),
        "user_id": identity
        if fullmatch(r"[1-9][0-9]{0,9}", identity)
        else None,
        "share": source["share"],
        "character_floor": character_floor,
        "prose_characters": source.get("prose_characters"),
        "raw_bytes": raw_bytes,
        "share_label": f"{source['share'] * 100:.1f}%",
        "characters_label": _number(source.get("prose_characters")),
        "bytes_label": f"{_kilobytes(raw_bytes)} kB"
        if raw_bytes is not None
        else "—",
        "bytes_title": _number(raw_bytes) if raw_bytes is not None else None,
    }


def _main_editors(proof: dict) -> list[dict]:
    """Require a share above 33% and 500 attributed characters.

    Returns:
        Saved editor observations that meet both thresholds.
    """
    if not proof["available"]:
        return []
    return [
        editor
        for editor in proof["editors"]
        if editor["share"] > MAIN_SHARE_THRESHOLD
        and editor["character_floor"] >= MAIN_MIN_CHARACTERS
    ]


def _main_contributors(proof: dict, interface: Interface) -> list[dict]:
    """Describe the authors of each article.

    Returns:
        Raw filter identities and separate display labels and links.
    """
    return [
        {
            "name": editor["name"],
            "label": interface.text("quality_analysis.anonymous_user")
            if editor["anonymous"]
            else editor["name"],
            "url": None if editor["anonymous"] else editor["url"],
        }
        for editor in _main_editors(proof)
    ]


def catalog_article(
    row: dict,
    interface: Interface,
    *,
    include_authorship: bool = True,
) -> list:
    """Encode one deferred article with consistent contributor roles.

    Returns:
        Compact article values, observed proof and display descriptors.
    """
    proof = _authorship(row, interface) if include_authorship else None
    main = _main_contributors(proof, interface) if proof else []
    return [
        *(
            (row.get(key) or "Unknown")
            if key == "importance"
            else row.get(key)
            for key in (
                "page_id",
                "title",
                "grade",
                "importance",
                "listed_date",
                "listed_oldid",
                "prose_characters",
                "source_bytes",
            )
        ),
        [editor["name"] for editor in main],
        display_title(row["title"].replace("_", " "), interface.locale),
        interface.date(row["listed_date"]) if row["listed_date"] else None,
        proof if proof and proof["available"] else None,
        review_url({
            "nomination_link": row.get("listed_review_link"),
            "title": row["title"],
        }),
        main,
    ]


def contributor_names(row: dict, interface: Interface) -> dict:
    """Use the same evidence thresholds in display and search.

    Returns:
        Display names and identities for the two contributor types.
    """
    proof = _authorship(row, interface)
    main = _main_contributors(proof, interface)
    return {
        "main": [editor["name"] for editor in main],
        "labels": [editor["label"] for editor in main],
        "significant": [editor["name"] for editor in proof["editors"]]
        if proof["available"]
        else [],
    }


def main_author_directory(
    articles: list[dict],
    authors: list[dict],
) -> list[dict]:
    """Apply the website threshold to the registered-author directory.

    Returns:
        Author records containing only articles meeting both thresholds.
    """
    interface = Interface("en")
    qualified = {}
    identities = defaultdict(set)
    names = defaultdict(set)
    contributions = defaultdict(list)
    for row in articles:
        proof = _authorship(row, interface)
        if proof["available"]:
            for editor in proof["editors"]:
                if editor["url"] and not editor["anonymous"]:
                    contributions[editor["name"]].append((
                        row["page_id"],
                        editor["prose_characters"],
                        editor["raw_bytes"],
                    ))
        editors = [
            author
            for author in _main_editors(proof)
            if author["url"] is not None and not author["anonymous"]
        ]
        qualified[row["page_id"]] = {author["name"] for author in editors}
        for author in editors:
            if user_id := author["user_id"]:
                identities[author["name"]].add(user_id)
                names[user_id].add(author["name"])
    output = []
    for author in authors:
        selected = [
            {
                **article,
                "coauthors": [
                    name
                    for name in article.get("coauthors", [])
                    if name in qualified.get(article.get("page_id"), set())
                ],
            }
            for article in author["articles"]
            if author["name"] in qualified.get(article.get("page_id"), set())
        ]
        if selected:
            ids = identities[author["name"]]
            user_id = next(iter(ids)) if len(ids) == 1 else None
            output.append({
                **author,
                "user_id": user_id if len(names[user_id]) == 1 else None,
                "articles": selected,
                "contributions": contributions[author["name"]],
                "credit": len(selected),
                "grades": {
                    grade: sum(
                        article["grade"] == grade for article in selected
                    )
                    for grade in author["grades"]
                },
            })
    return output


def author_contribution_totals(
    contributions: list[tuple[int, int | None, int | None]],
    page_ids: set[int] | None,
) -> dict[str, int | None]:
    """Sum the saved prose and byte counts within the selected cohort.

    Returns:
        Totals with null for a metric lacking any measured contribution.
    """
    prose = size = None
    for page_id, characters, raw_bytes in contributions:
        if page_ids is not None and page_id not in page_ids:
            continue
        if characters is not None:
            prose = (prose or 0) + characters
        if raw_bytes is not None:
            size = (size or 0) + raw_bytes
    return {"prose": prose, "bytes": size}


def _author_article(article: dict, prefix: str) -> dict:
    """Give each contributor dialog a unique attribution popup.

    Returns:
        An article row with a dialog-specific popup identifier.
    """
    return {
        **article,
        "authorship_popup_id": f"{prefix}-{article['authorship_popup_id']}",
    }


def prepare_author_articles(
    authors: list[dict],
    analysis: dict,
    interface: Interface,
) -> None:
    """Attach localized article rows and contribution totals."""
    page_ids = {
        page_id
        for author in authors
        for page_id, _, _ in author["contributions"]
    }
    if not page_ids:
        return
    selection = analysis.get("selection")
    selected_ids = (
        {
            row["page_id"]
            for row in selection["defaults"][
                int(bool(analysis.get("all_grades")))
            ]["articles"]
        }
        if selection
        else None
    )
    rows = _articles(
        {
            **analysis,
            "articles": [
                row
                for row in analysis["articles"]
                if row["page_id"] in page_ids
            ],
        },
        interface,
    )
    catalog = {
        row["page_id"]: {
            **row,
            "default_selected": selected_ids is None
            or row["page_id"] in selected_ids,
        }
        for row in rows
    }
    for author in authors:
        prefix = (
            f"quality-author-user-{author['user_id']}"
            if author["user_id"]
            else author["popup_id"]
        )
        author["articles"] = [
            _author_article(catalog[record["page_id"]], prefix)
            for record in author["articles"]
        ]
        significant_id = f"{prefix}-significant"
        author["significant_popup_id"] = significant_id
        author["significant_dialog_title"] = interface.text(
            "quality_authorship.author_significant_articles",
            name=author["name"],
        )
        author["significant_articles"] = [
            {
                **_author_article(catalog[page_id], significant_id),
                "prose_characters": prose,
                "characters_label": _number(prose),
                "source_bytes": size,
                "source_label": _kilobytes(size),
            }
            for page_id, prose, size in author["contributions"]
        ]
        totals = author_contribution_totals(
            author["contributions"],
            selected_ids,
        )
        author.update(
            contributed_prose=totals["prose"],
            contributed_prose_label=_number(totals["prose"]),
            contributed_bytes=totals["bytes"],
            contributed_bytes_label=_kilobytes(totals["bytes"]),
        )


def _coverage_cards(data: dict, interface: Interface) -> list[dict]:
    """Describe selected evidence counts with independent saved clocks.

    Returns:
        Four coverage cards without substituting award or render times.
    """
    rows = data.get("articles", [])
    selection = data.get("selection")
    if selection:
        variant = int(bool(data.get("all_grades")))
        identities = {
            row["page_id"]
            for row in selection["defaults"][variant]["articles"]
        }
        rows = [row for row in rows if row["page_id"] in identities]
    counts = {
        "total": len(rows),
        "authorship": sum(
            bool((row.get("authorship") or {}).get("available"))
            or bool(row.get("authorship_available"))
            for row in rows
        ),
        "dates": sum(row.get("listed_date") is not None for row in rows),
        "length": sum(row.get("prose_characters") is not None for row in rows),
    }
    clocks = {
        "total": data.get("observed_at"),
        "length": max(
            (row["measured_at"] for row in rows if row.get("measured_at")),
            default=None,
        ),
        **data.get("coverage_updated_at", {}),
    }
    return [
        {
            "key": key,
            "label": interface.text(f"quality_coverage.{key}"),
            "count": _number(count),
            "updated_at": clocks.get(key),
            "updated_label": utc_time(clocks.get(key)),
        }
        for key, count in counts.items()
    ]


def _matrix_grade_groups(
    grades: list[dict],
    interface: Interface,
) -> list[dict]:
    """Pair article and list grades using the assessment profile.

    Returns:
        Ordered labels and the article or list grades they select.
    """
    groups = {}
    for grade in grades:
        code = grade["value"]
        group = _GRADE_GROUPS[code]
        if group not in groups:
            groups[group] = {
                "value": group,
                "label": interface.text("quality_analysis.featured_grade")
                if group == "FA"
                else grade_label(group, interface),
                "grades": [],
            }
        kind = "article" if code == group else "list"
        groups[group]["grades"].append(
            {**grade, "kind": "unassessed" if code == "Unassessed" else kind},
        )
    return list(groups.values())


def quality_analysis_context(
    data: dict,
    interface: Interface,
    *,
    paged: bool = False,
) -> dict:
    """Localize saved metrics and lay out proportional chart marks.

    Args:
        data: Validated saved article rows and precomputed summaries.
        interface: Negotiated interface language.
        paged: Use a separate server-side directory for article details.

    Returns:
        Chart geometry and complete table rows, with explicit coverage.
    """
    coverage = data.get("coverage", {})
    total = coverage.get("total", 0)
    grades = _pie(data.get("grade_totals", []), "class", total, interface)
    importance = _pie(
        data.get("importance_totals", []),
        "importance",
        total,
        interface,
    )
    length_maximum = prose_length_maximum(data)
    lengths = _lengths(data, interface, length_maximum)
    length_lookup = {
        (row["group"], row["grade"] or row["importance"]): row
        for row in lengths
    }
    grades = [
        {**row, "length": length_lookup.get(("grade", row["grade"]))}
        for row in sorted(
            grades,
            key=lambda row: _DISTRIBUTION_GRADES.index(row["grade"]),
        )
    ]
    importance = [
        {**row, "length": length_lookup.get(("importance", row["importance"]))}
        for row in importance
    ]
    selection = data.get("selection")
    matrix = None
    shown = data.get("articles", [])
    if selection:
        defaults = selection["defaults"][int(bool(data.get("all_grades")))]
        ordered = defaults["articles"]
        if paged:
            ordered = sorted(
                ordered,
                key=lambda row: row.get("listed_date") or "",
                reverse=True,
            )
            positions = {
                row["page_id"]: index
                for index, row in enumerate(ordered[:ARTICLE_PAGE_SIZE])
            }
            shown = sorted(
                (row for row in shown if row["page_id"] in positions),
                key=lambda row: positions[row["page_id"]],
            )
        else:
            default_ids = {
                row["page_id"] for row in ordered[:ARTICLE_PAGE_SIZE]
            }
            shown = [row for row in shown if row["page_id"] in default_ids]
    if selection:
        codes = [
            code
            for code in _GRADES
            if code not in {"A", "AL"}
            or any(row["grade"] == code for row in selection["articles"])
        ]
        matrix = {
            "cells": selection["cells"],
            "assessment_comparison": data.get("assessment_comparison"),
            "length_scale_maximum": length_maximum,
            "extra": []
            if paged
            else [
                catalog_article(row, interface)
                for row in selection["articles"]
                if row["page_id"] not in default_ids
            ],
            "labels": {
                **{
                    key: interface.text(f"quality_analysis.{key}")
                    for key in (
                        "until",
                        "visualization",
                        "authorship_unavailable",
                        "no_top_editors",
                        "unknown_listing",
                        "contributors",
                        "authorship_note",
                        "editor_share",
                        "editor_bytes",
                        "editor_characters",
                        "editor_bytes_hint",
                        "editor_characters_hint",
                        "words",
                        "authorship_details",
                        "review",
                        "violin_summary",
                        "violin_range",
                        "violin_single",
                        "violin_minimum",
                        "violin_p25",
                        "violin_p50",
                        "violin_p75",
                        "violin_maximum",
                        "violin_mean",
                        "main_unavailable",
                        "no_main_contributors",
                        "anonymous_user",
                    )
                },
                "talk": interface.text("quality_authorship.talk"),
                "user": interface.text("quality_authorship.user"),
                "unknown": interface.text("data.unknown"),
                "parenthesis_open": interface.text(
                    "quality_authorship.parenthesis_open",
                ),
                "parenthesis_close": interface.text(
                    "quality_authorship.parenthesis_close",
                ),
            },
            "last_year": selection["last_year"],
            "grades": [
                {
                    "value": code,
                    "label": grade_label(code, interface),
                    "article_label": grade_label(code, interface),
                    "order": _GRADES.index(code),
                    "distribution_order": _DISTRIBUTION_GRADES.index(code),
                    "color": _assessment_color(code, "class"),
                    "checked": code
                    not in {
                        "B",
                        "BL",
                        "C",
                        "CL",
                        "Start",
                        "List",
                        "Stub",
                        "SL",
                        "Unassessed",
                    }
                    or data.get("all_grades"),
                }
                for code in codes
            ],
            "importance": [
                {
                    "value": code,
                    "label": interface.text(f"assessment.importance.{code}"),
                    "article_color": _assessment_color(code, "importance"),
                    "order": _IMPORTANCE.index(code),
                    "color": _assessment_color(code, "importance"),
                }
                for code in ("Top", "High", "Mid", "Low", "Unknown")
            ],
        }
    return {
        "quality_analysis": {
            "available": bool(data.get("available")),
            "page_sizes": ARTICLE_PAGE_SIZES,
            "matrix": matrix,
            "grade_groups": _matrix_grade_groups(matrix["grades"], interface)
            if matrix
            else [],
            "listing_authors": data.get("authorship_basis") == "listed",
            "total": _number(total),
            "coverage_cards": _coverage_cards(data, interface),
            "assessment_comparison": data.get("assessment_comparison"),
            "coverage_labels": {
                key: interface.text(f"quality_coverage.{key}")
                for key in (
                    "comparison",
                    "missing_authorship",
                    "missing_dates",
                    "missing_length",
                    "no_missing",
                    "comparison_unavailable",
                    "category",
                    "pageassessments",
                    "difference",
                    "only_categories",
                    "only_pageassessments",
                    "grade_mismatch",
                    "categories_updated",
                    "pa_updated",
                    "unknown_time",
                )
            },
            "measured": _number(coverage.get("measured", 0)),
            "dated": _number(coverage.get("dated", 0)),
            "unknown_dates": _number(total - coverage.get("dated", 0)),
            "median": _number(coverage.get("median_characters")),
            "all_grades": bool(data.get("all_grades")),
            "locale": interface.locale,
            "length_scale_maximum": length_maximum,
            "grades": grades,
            "importance_totals": importance,
            "importance_available": data.get("importance_available", True),
            **_years(data, interface),
            "year_table_grades": [
                grade for grade in matrix["grades"] if grade["checked"]
            ]
            if matrix
            else [
                {"value": code, "label": grade_label(code, interface)}
                for code in _GRADES
                if any(
                    row["grade"] == code
                    for row in data.get("grade_totals", [])
                )
            ],
            "lengths": lengths,
            "lengths_available": data.get("lengths_available", True),
            "grade_lengths": [
                row for row in lengths if row["group"] == "grade"
            ],
            "importance_lengths": [
                row for row in lengths if row["group"] == "importance"
            ],
            "articles": _articles({**data, "articles": shown}, interface),
            "grade_options": matrix["grades"]
            if matrix
            else [
                {
                    "value": code,
                    "label": grade_label(code, interface),
                }
                for code in _GRADES
                if data.get("all_grades") or code not in {"B", "BL"}
                if code not in {"A", "AL"}
                or any(row["grade"] == code for row in grades)
            ],
            "importance_options": [
                {
                    "value": code,
                    "label": interface.text(f"assessment.importance.{code}"),
                }
                for code in (
                    *_IMPORTANCE,
                    *(("Unknown",) if "Unknown" not in _IMPORTANCE else ()),
                )
            ],
        },
    }
