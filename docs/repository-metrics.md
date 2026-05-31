# Repository Metrics

The `Update clone metrics` workflow records GitHub Traffic API clone aggregates on the independent `repo-metrics` branch.

## One-time Setup

1. Create a fine-grained personal access token scoped to this repository with `Administration: read`.
2. Save it as the repository Actions secret `TRAFFIC_READ_TOKEN`.
3. Allow GitHub Actions to write repository contents.
4. Run `Update clone metrics` manually once before announcing the chart.

The first run creates the `repo-metrics` branch with `clone-history.json` and `clone-history.svg`. Later runs merge GitHub's rolling Traffic API window into permanent daily history.

The chart is an operational indicator. Clone counts can include bots, CI jobs, and repeated pulls, so they must not be described as verified users.
