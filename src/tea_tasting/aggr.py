"""Module for working with aggregated statistics: count, mean, var, cov."""
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, overload

import tea_tasting._utils


if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

    from ibis.expr.types import Table
    from pandas import DataFrame


_COUNT = "_count"
_MEAN = "_mean__{}"
_VAR = "_var__{}"
_COV = "_cov__{}__{}"
_DEMEAN = "_demean__{}"


class Aggregates:
    """Aggregated statistics."""
    _count: int | None
    _mean: dict[str, float | int]
    _var: dict[str, float | int]
    _cov: dict[tuple[str, str], float | int]

    def __init__(
        self: Aggregates,
        count: int | None,
        mean: dict[str, float | int],
        var: dict[str, float | int],
        cov: dict[tuple[str, str], float | int],
    ) -> None:
        """Create an object with aggregated statistics.

        Args:
            count: Sample size.
            mean: Variables sample means.
            var: Variables sample variances.
            cov: Pairs of variables sample covariances.
        """
        self._count = count
        self._mean = mean
        self._var = var
        self._cov = {
            tea_tasting._utils.sorted_tuple(left, right): value
            for (left, right), value in cov.items()
        }

    def __repr__(self: Aggregates) -> str:
        """Object representation."""
        return (
            f"Aggregates(count={self._count!r}, mean={self._mean!r}, "
            f"var={self._var!r}, cov={self._cov!r})"
        )

    def count(self: Aggregates) -> int:
        """Sample size.

        Raises:
            RuntimeError: Count is None (it wasn't defined at init).

        Returns:
            Number of observations.
        """
        if self._count is None:
            raise RuntimeError("Count is None.")
        return self._count

    def mean(self: Aggregates, key: str | None) -> float | int:
        """Sample mean.

        Args:
            key: Variable name.

        Returns:
            Sample mean.
        """
        if key is None:
            return 1
        return self._mean[key]

    def var(self: Aggregates, key: str | None) -> float | int:
        """Sample variance.

        Args:
            key: Variable name.

        Returns:
            Sample variance.
        """
        if key is None:
            return 0
        return self._var[key]

    def cov(self: Aggregates, left: str | None, right: str | None) -> float | int:
        """Sample covariance.

        Args:
            left: First variable name.
            right: Second variable name.

        Returns:
            Sample covariance.
        """
        if left is None or right is None:
            return 0
        return self._cov[tea_tasting._utils.sorted_tuple(left, right)]

    def ratio_var(
        self: Aggregates,
        numer: str | None,
        denom: str | None,
    ) -> float | int:
        """Sample variance of the ratio of two variables using the Delta method.

        References:
            [Delta method](https://en.wikipedia.org/wiki/Delta_method).
            [Taylor expansions for the moments of functions of random variables](https://en.wikipedia.org/wiki/Taylor_expansions_for_the_moments_of_functions_of_random_variables).

        Args:
            numer: Numerator variable name.
            denom: Denominator variable name.

        Returns:
            Sample variance of the ratio of two variables.
        """
        denom_mean_sq = self.mean(denom) * self.mean(denom)
        return (
            self.var(numer)
            - 2 * self.cov(numer, denom) * self.mean(numer) / self.mean(denom)
            + self.var(denom) * self.mean(numer) * self.mean(numer) / denom_mean_sq
        ) / denom_mean_sq

    def ratio_cov(
        self: Aggregates,
        left_numer: str | None,
        left_denom: str | None,
        right_numer: str | None,
        right_denom: str | None,
    ) -> float | int:
        """Sample covariance of the ratios of variables using the Delta method.

        References:
            [Delta method](https://en.wikipedia.org/wiki/Delta_method).
            [Taylor expansions for the moments of functions of random variables](https://en.wikipedia.org/wiki/Taylor_expansions_for_the_moments_of_functions_of_random_variables).

        Args:
            left_numer: First numerator variable name.
            left_denom: First denominator variable name.
            right_numer: Second numerator variable name.
            right_denom: Second denominator variable name.

        Returns:
            Sample covariance of the ratios of variables.
        """
        left_ratio_of_means = self.mean(left_numer) / self.mean(left_denom)
        right_ratio_of_means = self.mean(right_numer) / self.mean(right_denom)
        return (
            self.cov(left_numer, right_numer)
            - self.cov(left_numer, right_denom) * right_ratio_of_means
            - self.cov(left_denom, right_numer) * left_ratio_of_means
            + self.cov(left_denom, right_denom)
                * left_ratio_of_means * right_ratio_of_means
        ) / self.mean(left_denom) / self.mean(right_denom)

    def filter(
        self: Aggregates,
        has_count: bool,
        mean_cols: Sequence[str],
        var_cols: Sequence[str],
        cov_cols: Sequence[tuple[str, str]],
    ) -> Aggregates:
        """Filter aggregated statistics.

        Args:
            has_count: If True, keep sample size in the resulting object.
            mean_cols: Sample means variable names.
            var_cols: Sample variances variable names.
            cov_cols: Sample covariances variable names.

        Returns:
            Filtered aggregated statistics.
        """
        has_count, mean_cols, var_cols, cov_cols = _validate_aggr_cols(
            has_count, mean_cols, var_cols, cov_cols)

        return Aggregates(
            count=self.count() if has_count else None,
            mean={col: self.mean(col) for col in mean_cols},
            var={col: self.var(col) for col in var_cols},
            cov={cols: self.cov(*cols) for cols in cov_cols},
        )

    def __add__(self: Aggregates, other: Aggregates) -> Aggregates:
        """Calculate aggregated statistics of the concatenation of two samples.

        Samples are assumed to be independent.

        Args:
            other: Aggregated statistics of the second sample.

        Returns:
            Aggregated statistics of the concatenation of two samples.
        """
        return Aggregates(
            count=self.count() + other.count() if self._count is not None else None,
            mean={col: _add_mean(self, other, col) for col in self._mean},
            var={col: _add_var(self, other, col) for col in self._var},
            cov={cols: _add_cov(self, other, cols) for cols in self._cov},
        )


def _add_mean(left: Aggregates, right: Aggregates, col: str) -> float | int:
    sum_ = left.count()*left.mean(col) + right.count()*right.mean(col)
    count = left.count() + right.count()
    return sum_ / count

def _add_var(left: Aggregates, right: Aggregates, col: str) -> float | int:
    left_n = left.count()
    right_n = right.count()
    total_n = left_n + right_n
    diff_of_means = left.mean(col) - right.mean(col)
    return (
        left.var(col) * (left_n - 1)
        + right.var(col) * (right_n - 1)
        + diff_of_means * diff_of_means * left_n * right_n / total_n
    ) / (total_n - 1)

def _add_cov(left: Aggregates, right: Aggregates, cols: tuple[str, str]) -> float | int:
    left_n = left.count()
    right_n = right.count()
    total_n = left_n + right_n
    diff_of_means0 = left.mean(cols[0]) - right.mean(cols[0])
    diff_of_means1 = left.mean(cols[1]) - right.mean(cols[1])
    return (
        left.cov(*cols) * (left_n - 1)
        + right.cov(*cols) * (right_n - 1)
        + diff_of_means0 * diff_of_means1 * left_n * right_n / total_n
    ) / (total_n - 1)


@overload
def read_aggregates(
    data: Table,
    group_col: str,
    has_count: bool,
    mean_cols: Sequence[str],
    var_cols: Sequence[str],
    cov_cols: Sequence[tuple[str, str]],
) -> dict[Any, Aggregates]:
    ...

@overload
def read_aggregates(
    data: Table,
    group_col: None,
    has_count: bool,
    mean_cols: Sequence[str],
    var_cols: Sequence[str],
    cov_cols: Sequence[tuple[str, str]],
) -> Aggregates:
    ...

def read_aggregates(
    data: Table,
    group_col: str | None,
    has_count: bool,
    mean_cols: Sequence[str],
    var_cols: Sequence[str],
    cov_cols: Sequence[tuple[str, str]],
) -> dict[Any, Aggregates] | Aggregates:
    """Read aggregated statistics from an Ibis Table.

    Args:
        data: Ibis Table.
        group_col: Column name to group by before aggregation.
        has_count: If True, calculate the sample size.
        mean_cols: Column names for calculation of sample means.
        var_cols: Column names for calculation of sample variances.
        cov_cols: Pairs of column names for calculation of sample covariances.

    Returns:
        Aggregated statistics from the Ibis Table.
    """
    has_count, mean_cols, var_cols, cov_cols = _validate_aggr_cols(
        has_count, mean_cols, var_cols, cov_cols)

    demean_cols = tuple({*var_cols, *itertools.chain(*cov_cols)})
    if len(demean_cols) > 0:
        demean_expr = {
            _DEMEAN.format(col): data[col] - data[col].mean()  # type: ignore
            for col in demean_cols
        }
        grouped_data = data.group_by(group_col) if group_col is not None else data
        data = grouped_data.mutate(**demean_expr)

    count_expr = {_COUNT: data.count()} if has_count else {}
    mean_expr = {_MEAN.format(col): data[col].mean() for col in mean_cols}  # type: ignore
    var_expr = {
        _VAR.format(col): (
            data[_DEMEAN.format(col)] * data[_DEMEAN.format(col)]
        ).sum().cast("float") / (data.count() - 1)  # type: ignore
        for col in var_cols
    }
    cov_expr = {
        _COV.format(left, right): (
            data[_DEMEAN.format(left)] * data[_DEMEAN.format(right)]
        ).sum().cast("float") / (data.count() - 1)  # type: ignore
        for left, right in cov_cols
    }

    grouped_data = data.group_by(group_col) if group_col is not None else data
    aggr_data = grouped_data.aggregate(
        **count_expr,
        **mean_expr,
        **var_expr,
        **cov_expr,
    ).to_pandas()

    if group_col is None:
        return _get_aggregates(
            aggr_data,
            has_count=has_count,
            mean_cols=mean_cols,
            var_cols=var_cols,
            cov_cols=cov_cols,
        )

    return {
        group: _get_aggregates(
            group_data,
            has_count=has_count,
            mean_cols=mean_cols,
            var_cols=var_cols,
            cov_cols=cov_cols,
        )
        for group, group_data in aggr_data.groupby(group_col)
    }


def _get_aggregates(
    data: DataFrame,
    has_count: bool,
    mean_cols: Sequence[str],
    var_cols: Sequence[str],
    cov_cols: Sequence[tuple[str, str]],
) -> Aggregates:
    s = data.iloc[0]
    return Aggregates(
        count=s[_COUNT] if has_count else None,
        mean={col: s[_MEAN.format(col)] for col in mean_cols},
        var={col: s[_VAR.format(col)] for col in var_cols},
        cov={cols: s[_COV.format(*cols)] for cols in cov_cols},
    )


def _validate_aggr_cols(
    has_count: bool,
    mean_cols: Sequence[str],
    var_cols: Sequence[str],
    cov_cols: Sequence[tuple[str, str]],
) -> tuple[bool, tuple[str, ...], tuple[str, ...], tuple[tuple[str, str], ...]]:
    has_count = has_count or len(var_cols) > 0 or len(cov_cols) > 0
    mean_cols = tuple({*mean_cols, *var_cols, *itertools.chain(*cov_cols)})
    var_cols = tuple(set(var_cols))
    cov_cols = tuple({
        tea_tasting._utils.sorted_tuple(left, right)
        for left, right in cov_cols
    })
    return has_count, mean_cols, var_cols, cov_cols
