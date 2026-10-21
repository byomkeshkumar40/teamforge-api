import pytest

from tests.helpers import API, auth_headers, create_org, create_project, create_task, join_org


def turl(org_id):
    return f"{API}/organizations/{org_id}/tasks"


@pytest.fixture
def board(client, make_user):
    """One org, two projects, five tasks with varied attributes, plus noise in another org."""
    owner, ann, ben = make_user(), make_user(), make_user()
    org = create_org(client, owner)
    join_org(client, org["id"], owner, ann)
    join_org(client, org["id"], owner, ben)
    p1 = create_project(client, org["id"], owner, "Alpha")
    p2 = create_project(client, org["id"], owner, "Beta")

    def add(title, project, **fields):
        return create_task(client, org["id"], owner, project["id"], title, **fields)["id"]

    ids = {
        "docs": add(
            "Write docs",
            p1,
            status="TODO",
            priority="LOW",
            due_date="2030-01-10",
            assignee_id=str(ann.id),
        ),
        "bug": add(
            "Fix login bug",
            p1,
            status="IN_PROGRESS",
            priority="HIGH",
            due_date="2030-01-05",
            assignee_id=str(ben.id),
        ),
        "deploy": add("Deploy", p1, status="IN_REVIEW", priority="URGENT"),
        "pr": add(
            "Review PR 100%_ready",
            p1,
            status="DONE",
            priority="MEDIUM",
            due_date="2030-02-01",
            assignee_id=str(ann.id),
        ),
        "sprint": add("Plan sprint", p2, status="TODO", priority="HIGH", due_date="2030-01-20"),
    }
    # noise: a different tenant whose tasks must never appear
    other = make_user()
    other_org = create_org(client, other, "Other")
    other_project = create_project(client, other_org["id"], other)
    for i in range(3):
        create_task(
            client,
            other_org["id"],
            other,
            other_project["id"],
            f"Other {i}",
            status="TODO",
            priority="URGENT",
        )
    return {"org": org, "owner": owner, "ann": ann, "ben": ben, "p1": p1, "p2": p2, "ids": ids}


def query(client, board, params=""):
    response = client.get(
        f"{turl(board['org']['id'])}{params}", headers=auth_headers(board["owner"])
    )
    assert response.status_code == 200, response.text
    return response.json()


def found(client, board, params=""):
    ids = board["ids"]
    reverse = {v: k for k, v in ids.items()}
    return {reverse[t["id"]] for t in query(client, board, params)["items"]}


def ordered(client, board, params=""):
    reverse = {v: k for k, v in board["ids"].items()}
    return [reverse[t["id"]] for t in query(client, board, params)["items"]]


def test_unfiltered_list_contains_only_this_tenants_tasks(client, board):
    body = query(client, board)
    assert body["total"] == 5 and found(client, board) == set(board["ids"])


def test_filter_by_status(client, board):
    assert found(client, board, "?status=TODO") == {"docs", "sprint"}
    assert found(client, board, "?status=TODO&status=DONE") == {"docs", "sprint", "pr"}


def test_filter_by_priority(client, board):
    assert found(client, board, "?priority=HIGH") == {"bug", "sprint"}
    assert found(client, board, "?priority=HIGH&priority=URGENT") == {"bug", "sprint", "deploy"}


def test_filter_by_assignee_and_unassigned(client, board):
    assert found(client, board, f"?assignee_id={board['ann'].id}") == {"docs", "pr"}
    assert found(client, board, "?unassigned=true") == {"deploy", "sprint"}


def test_filter_by_project(client, board):
    assert found(client, board, f"?project_id={board['p2']['id']}") == {"sprint"}


def test_filter_by_due_date_range_is_inclusive(client, board):
    assert found(client, board, "?due_before=2030-01-10") == {"bug", "docs"}
    assert found(client, board, "?due_after=2030-01-20") == {"sprint", "pr"}
    assert found(client, board, "?due_after=2030-01-05&due_before=2030-01-10") == {"bug", "docs"}
    # tasks without a due date never match a date filter
    assert "deploy" not in found(client, board, "?due_after=2000-01-01&due_before=2100-01-01")


def test_title_search_is_literal_and_case_insensitive(client, board):
    assert found(client, board, "?q=LOGIN") == {"bug"}
    assert found(client, board, "?q=%25_ready") == {"pr"}  # "%_ready" matches literally
    assert found(client, board, "?q=%25") == {"pr"}  # a lone % is not a wildcard


def test_filters_combine_with_and(client, board):
    assert found(client, board, f"?status=TODO&priority=HIGH&project_id={board['p2']['id']}") == {
        "sprint"
    }
    assert found(client, board, f"?assignee_id={board['ann'].id}&status=DONE") == {"pr"}


def test_filtering_by_another_tenants_ids_returns_nothing(client, board, make_user):
    outsider = make_user()
    other_org = create_org(client, outsider, "X")
    other_project = create_project(client, other_org["id"], outsider)
    assert query(client, board, f"?project_id={other_project['id']}")["total"] == 0
    assert query(client, board, f"?assignee_id={outsider.id}")["total"] == 0


# ------------------------------------------------------------------- sorting


def test_sort_by_priority_uses_semantic_order(client, board):
    low_first = ordered(client, board, "?sort_by=priority&order=asc")
    assert low_first[0] == "docs" and low_first[1] == "pr" and low_first[-1] == "deploy"
    assert ordered(client, board, "?sort_by=priority&order=desc")[0] == "deploy"


def test_sort_by_status_follows_workflow_order(client, board):
    order = ordered(client, board, "?sort_by=status&order=asc")
    assert (
        order[-1] == "pr" and order[-2] == "deploy" and order[2] == "bug"
    )  # DONE last, IN_PROGRESS 3rd


def test_sort_by_due_date_puts_missing_dates_last_in_both_directions(client, board):
    assert ordered(client, board, "?sort_by=due_date&order=asc") == [
        "bug",
        "docs",
        "sprint",
        "pr",
        "deploy",
    ]
    assert ordered(client, board, "?sort_by=due_date&order=desc") == [
        "pr",
        "sprint",
        "docs",
        "bug",
        "deploy",
    ]


def test_sort_by_title(client, board):
    assert ordered(client, board, "?sort_by=title&order=asc") == [
        "deploy",
        "bug",
        "sprint",
        "pr",
        "docs",
    ]


def test_default_sort_is_newest_first(client, board):
    first = query(client, board)["items"]
    assert [t["created_at"] for t in first] == sorted(
        (t["created_at"] for t in first), reverse=True
    )


# ---------------------------------------------------------------- pagination


def test_pagination_pages_are_disjoint_and_complete(client, board):
    seen = []
    for offset in (0, 2, 4):
        page = query(client, board, f"?limit=2&offset={offset}&sort_by=priority")
        assert page["total"] == 5 and page["limit"] == 2 and page["offset"] == offset
        seen += [t["id"] for t in page["items"]]
    assert len(seen) == 5 and set(seen) == set(board["ids"].values())


def test_offset_past_the_end_returns_empty_page(client, board):
    page = query(client, board, "?offset=500")
    assert page["items"] == [] and page["total"] == 5


# ---------------------------------------------------------- invalid parameters


@pytest.mark.parametrize(
    "params",
    [
        "?limit=0",
        "?limit=101",
        "?limit=-5",
        "?offset=-1",
        "?offset=abc",
        "?status=BOGUS",
        "?priority=EXTREME",
        "?assignee_id=nope",
        "?project_id=nope",
        "?due_before=yesterday",
        "?due_after=2030-99-99",
        "?unassigned=maybe",
        "?q=",
        "?q=" + "x" * 101,
        "?sort_by=password_hash",
        "?sort_by=organization_id",
        "?sort_by=created_at;DROP TABLE tasks",
        "?sort_by=title)%20DESC,%20(SELECT%201",
        "?order=up",
    ],
)
def test_invalid_query_parameters_are_rejected_with_422(client, board, params):
    response = client.get(
        f"{turl(board['org']['id'])}{params}", headers=auth_headers(board["owner"])
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_contradictory_filters_are_rejected(client, board):
    ann = board["ann"].id
    for params in (
        f"?assignee_id={ann}&unassigned=true",
        "?due_after=2030-02-01&due_before=2030-01-01",
    ):
        response = client.get(
            f"{turl(board['org']['id'])}{params}", headers=auth_headers(board["owner"])
        )
        assert response.status_code == 422


def test_maximum_page_size_is_honoured(client, board):
    assert query(client, board, "?limit=100")["limit"] == 100
