# Copyright 2018 The TensorFlow Probability Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""Implements the Hager-Zhang inexact line search algorithm.

Line searches are a central component for many optimization algorithms (e.g.
BFGS, conjugate gradient etc). Most of the sophisticated line search methods
aim to find a step length in a given search direction so that the step length
satisfies the
[Wolfe conditions](https://en.wikipedia.org/wiki/Wolfe_conditions).
[Hager-Zhang 2006](http://users.clas.ufl.edu/hager/papers/CG/cg_compare.pdf)
algorithm is a refinement of the commonly used
[More-Thuente](https://dl.acm.org/citation.cfm?id=192132) algorithm.

This module implements the Hager-Zhang algorithm.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections

import numpy as np
import tensorflow as tf
from tensorflow_probability.python.internal import prefer_static
from tensorflow_probability.python.optimizer.linesearch.internal import hager_zhang_lib as hzl

__all__ = [
    'hager_zhang',
]


def _machine_eps(dtype):
  """Returns the machine epsilon for the supplied dtype."""
  if isinstance(dtype, tf.DType):
    dtype = dtype.as_numpy_dtype()
  return np.finfo(dtype).eps


HagerZhangLineSearchResult = collections.namedtuple(
    'HagerZhangLineSearchResults', [
        'converged',  # Whether a point satisfying Wolfe/Approx wolfe was found.
        'failed',  # Whether the line search failed. It can fail if either the
                   # objective function or the gradient are not finite at
                   # an evaluation point.
        'func_evals',  # Number of function evaluations made.
        'iterations',  # Number of line search iterations made.
        'left',  # The left end point of the final bracketing interval.
                 # If converged is True, it is equal to `right`.
                 # Otherwise, it corresponds to the last interval computed.
        'right'  # The right end point of the final bracketing interval.
                 # If converged is True, it is equal to `left`.
                 # Otherwise, it corresponds to the last interval computed.
    ])


def hager_zhang(value_and_gradients_function,
                initial_step_size=None,
                value_at_initial_step=None,
                value_at_zero=None,
                converged=None,
                threshold_use_approximate_wolfe_condition=1e-6,
                shrinkage_param=0.66,
                expansion_param=5.0,
                sufficient_decrease_param=0.1,
                curvature_param=0.9,
                step_size_shrink_param=0.1,
                max_iterations=50,
                name=None):
  """The Hager Zhang line search algorithm.

  Performs an inexact line search based on the algorithm of
  [Hager and Zhang (2006)][2].
  The univariate objective function `value_and_gradients_function` is typically
  generated by projecting a multivariate objective function along a search
  direction. Suppose the multivariate function to be minimized is
  `g(x1,x2, .. xn)`. Let (d1, d2, ..., dn) be the direction along which we wish
  to perform a line search. Then the projected univariate function to be used
  for line search is

  ```None
    f(a) = g(x1 + d1 * a, x2 + d2 * a, ..., xn + dn * a)
  ```

  The directional derivative along (d1, d2, ..., dn) is needed for this
  procedure. This also corresponds to the derivative of the projected function
  `f(a)` with respect to `a`. Note that this derivative must be negative for
  `a = 0` if the direction is a descent direction.

  The usual stopping criteria for the line search is the satisfaction of the
  (weak) Wolfe conditions. For details of the Wolfe conditions, see
  ref. [3]. On a finite precision machine, the exact Wolfe conditions can
  be difficult to satisfy when one is very close to the minimum and as argued
  by [Hager and Zhang (2005)][1], one can only expect the minimum to be
  determined within square root of machine precision. To improve the situation,
  they propose to replace the Wolfe conditions with an approximate version
  depending on the derivative of the function which is applied only when one
  is very close to the minimum. The following algorithm implements this
  enhanced scheme.

  ### Usage:

  Primary use of line search methods is as an internal component of a class of
  optimization algorithms (called line search based methods as opposed to
  trust region methods). Hence, the end user will typically not want to access
  line search directly. In particular, inexact line search should not be
  confused with a univariate minimization method. The stopping criteria of line
  search is the satisfaction of Wolfe conditions and not the discovery of the
  minimum of the function.

  With this caveat in mind, the following example illustrates the standalone
  usage of the line search.

  ```python
    # Define value and gradient namedtuple
    ValueAndGradient = namedtuple('ValueAndGradient', ['x', 'f', 'df'])
    # Define a quadratic target with minimum at 1.3.
    def value_and_gradients_function(x):
      return ValueAndGradient(x=x, f=(x - 1.3) ** 2, df=2 * (x-1.3))
    # Set initial step size.
    step_size = tf.constant(0.1)
    ls_result = tfp.optimizer.linesearch.hager_zhang(
        value_and_gradients_function, initial_step_size=step_size)
    # Evaluate the results.
    with tf.Session() as session:
      results = session.run(ls_result)
      # Ensure convergence.
      assert results.converged
      # If the line search converged, the left and the right ends of the
      # bracketing interval are identical.
      assert results.left.x == result.right.x
      # Print the number of evaluations and the final step size.
      print ("Final Step Size: %f, Evaluations: %d" % (results.left.x,
                                                       results.func_evals))
  ```

  ### References:
  [1]: William Hager, Hongchao Zhang. A new conjugate gradient method with
    guaranteed descent and an efficient line search. SIAM J. Optim., Vol 16. 1,
    pp. 170-172. 2005.
    https://www.math.lsu.edu/~hozhang/papers/cg_descent.pdf

  [2]: William Hager, Hongchao Zhang. Algorithm 851: CG_DESCENT, a conjugate
    gradient method with guaranteed descent. ACM Transactions on Mathematical
    Software, Vol 32., 1, pp. 113-137. 2006.
    http://users.clas.ufl.edu/hager/papers/CG/cg_compare.pdf

  [3]: Jorge Nocedal, Stephen Wright. Numerical Optimization. Springer Series in
    Operations Research. pp 33-36. 2006

  Args:
    value_and_gradients_function: A Python callable that accepts a real scalar
      tensor and returns a namedtuple with the fields 'x', 'f', and 'df' that
      correspond to scalar tensors of real dtype containing the point at which
      the function was evaluated, the value of the function, and its
      derivative at that point. The other namedtuple fields, if present,
      should be tensors or sequences (possibly nested) of tensors.
      In usual optimization application, this function would be generated by
      projecting the multivariate objective function along some specific
      direction. The direction is determined by some other procedure but should
      be a descent direction (i.e. the derivative of the projected univariate
      function must be negative at 0.).
      Alternatively, the function may represent the batching of `n` such line
      functions (e.g. projecting a single multivariate objective function along
      `n` distinct directions at once) accepting n points as input, i.e. a
      tensor of shape [n], and the fields 'x', 'f' and 'df' in the returned
      namedtuple should each be a tensor of shape [n], with the corresponding
      input points, function values, and derivatives at those input points.
    initial_step_size: (Optional) Scalar positive `Tensor` of real dtype, or
      a tensor of shape [n] in batching mode. The initial value (or values) to
      try to bracket the minimum. Default is `1.` as a float32.
      Note that this point need not necessarily bracket the minimum for the line
      search to work correctly but the supplied value must be greater than 0.
      A good initial value will make the search converge faster.
    value_at_initial_step: (Optional) The full return value of evaluating
      value_and_gradients_function at initial_step_size, i.e. a namedtuple with
      'x', 'f', 'df', if already known by the caller. If supplied the value of
      `initial_step_size` will be ignored, otherwise the tuple will be computed
      by evaluating value_and_gradients_function.
    value_at_zero: (Optional) The full return value of
      value_and_gradients_function at `0.`, i.e. a namedtuple with
      'x', 'f', 'df', if already known by the caller. If not supplied the tuple
      will be computed by evaluating value_and_gradients_function.
    converged: (Optional) In batching mode a tensor of shape [n], indicating
      batch members which have already converged and no further search should
      be performed. These batch members are also reported as converged in the
      output, and both their `left` and `right` are set to the
      `value_at_initial_step`.
    threshold_use_approximate_wolfe_condition: Scalar positive `Tensor`
      of real dtype. Corresponds to the parameter 'epsilon' in
      [Hager and Zhang (2006)][2]. Used to estimate the
      threshold at which the line search switches to approximate Wolfe
      conditions.
    shrinkage_param: Scalar positive Tensor of real dtype. Must be less than
      `1.`. Corresponds to the parameter `gamma` in
      [Hager and Zhang (2006)][2].
      If the secant**2 step does not shrink the bracketing interval by this
      proportion, a bisection step is performed to reduce the interval width.
    expansion_param: Scalar positive `Tensor` of real dtype. Must be greater
      than `1.`. Used to expand the initial interval in case it does not bracket
      a minimum. Corresponds to `rho` in [Hager and Zhang (2006)][2].
    sufficient_decrease_param: Positive scalar `Tensor` of real dtype.
      Bounded above by the curvature param. Corresponds to `delta` in the
      terminology of [Hager and Zhang (2006)][2].
    curvature_param: Positive scalar `Tensor` of real dtype. Bounded above
      by `1.`. Corresponds to 'sigma' in the terminology of
      [Hager and Zhang (2006)][2].
    step_size_shrink_param: Positive scalar `Tensor` of real dtype. Bounded
      above by `1`. If the supplied step size is too big (i.e. either the
      objective value or the gradient at that point is infinite), this factor
      is used to shrink the step size until it is finite.
    max_iterations: Positive scalar `Tensor` of integral dtype or None. The
      maximum number of iterations to perform in the line search. The number of
      iterations used to bracket the minimum are also counted against this
      parameter.
    name: (Optional) Python str. The name prefixed to the ops created by this
      function. If not supplied, the default name 'hager_zhang' is used.

  Returns:
    results: A namedtuple containing the following attributes.
      converged: Boolean `Tensor` of shape [n]. Whether a point satisfying
        Wolfe/Approx wolfe was found.
      failed: Boolean `Tensor` of shape [n]. Whether line search failed e.g.
        if either the objective function or the gradient are not finite at
        an evaluation point.
      iterations: Scalar int32 `Tensor`. Number of line search iterations made.
      func_evals: Scalar int32 `Tensor`. Number of function evaluations made.
      left: A namedtuple, as returned by value_and_gradients_function,
        of the left end point of the final bracketing interval. Values are
        equal to those of `right` on batch members where converged is True.
        Otherwise, it corresponds to the last interval computed.
      right: A namedtuple, as returned by value_and_gradients_function,
        of the right end point of the final bracketing interval. Values are
        equal to those of `left` on batch members where converged is True.
        Otherwise, it corresponds to the last interval computed.
  """
  with tf.compat.v1.name_scope(name, 'hager_zhang', [
      initial_step_size, value_at_initial_step, value_at_zero, converged,
      threshold_use_approximate_wolfe_condition, shrinkage_param,
      expansion_param, sufficient_decrease_param, curvature_param]):
    val_0, val_initial, f_lim, prepare_evals = _prepare_args(
        value_and_gradients_function,
        initial_step_size,
        value_at_initial_step,
        value_at_zero,
        threshold_use_approximate_wolfe_condition)

    valid_inputs = (hzl.is_finite(val_0) & (val_0.df < 0) &
                    tf.math.is_finite(val_initial.x) & (val_initial.x > 0))

    if converged is None:
      init_converged = tf.zeros_like(valid_inputs)  # i.e. all false.
    else:
      init_converged = tf.convert_to_tensor(value=converged)

    failed = ~init_converged & ~valid_inputs
    active = ~init_converged & valid_inputs

    # Note: _fix_step_size returns immediately if either all inputs are invalid
    # or none of the active ones need fixing.
    fix_step_evals, val_c, fix_failed = _fix_step_size(
        value_and_gradients_function, val_initial, active,
        step_size_shrink_param)

    init_interval = HagerZhangLineSearchResult(
        converged=init_converged,
        failed=failed | fix_failed,
        func_evals=prepare_evals + fix_step_evals,
        iterations=tf.convert_to_tensor(value=0),
        left=val_0,
        right=hzl.val_where(init_converged, val_0, val_c))

    def _apply_bracket_and_search():
      """Bracketing and searching to do for valid inputs."""
      return _bracket_and_search(
          value_and_gradients_function, init_interval, f_lim, max_iterations,
          shrinkage_param, expansion_param, sufficient_decrease_param,
          curvature_param)

    init_active = ~init_interval.failed & ~init_interval.converged
    return prefer_static.cond(
        tf.reduce_any(input_tensor=init_active),
        _apply_bracket_and_search,
        lambda: init_interval)


def _fix_step_size(value_and_gradients_function,
                   val_c_input,
                   active,
                   step_size_shrink_param):
  """Shrinks the input step size until the value and grad become finite."""
  # The maximum iterations permitted are determined as the number of halvings
  # it takes to reduce 1 to 0 in the given dtype.
  iter_max = np.ceil(-np.log2(_machine_eps(val_c_input.x.dtype)))

  def _cond(i, val_c, to_fix):
    del val_c  # Unused.
    return (i < iter_max) & tf.reduce_any(input_tensor=to_fix)

  def _body(i, val_c, to_fix):
    next_c = tf.compat.v1.where(to_fix, val_c.x * step_size_shrink_param,
                                val_c.x)
    next_val_c = value_and_gradients_function(next_c)
    still_to_fix = to_fix & ~hzl.is_finite(next_val_c)
    return (i + 1, next_val_c, still_to_fix)

  to_fix = active & ~hzl.is_finite(val_c_input)
  return tf.while_loop(
      cond=_cond, body=_body, loop_vars=(0, val_c_input, to_fix))


_LineSearchInnerResult = collections.namedtuple('_LineSearchInnerResult', [
    'iteration',
    'found_wolfe',
    'failed',
    'num_evals',
    'left',
    'right'])


def _bracket_and_search(
    value_and_gradients_function,
    init_interval,
    f_lim,
    max_iterations,
    shrinkage_param,
    expansion_param,
    sufficient_decrease_param,
    curvature_param):
  """Brackets the minimum and performs a line search.

  Args:
    value_and_gradients_function: A Python callable that accepts a real scalar
      tensor and returns a namedtuple with the fields 'x', 'f', and 'df' that
      correspond to scalar tensors of real dtype containing the point at which
      the function was evaluated, the value of the function, and its
      derivative at that point. The other namedtuple fields, if present,
      should be tensors or sequences (possibly nested) of tensors.
      In usual optimization application, this function would be generated by
      projecting the multivariate objective function along some specific
      direction. The direction is determined by some other procedure but should
      be a descent direction (i.e. the derivative of the projected univariate
      function must be negative at 0.).
      Alternatively, the function may represent the batching of `n` such line
      functions (e.g. projecting a single multivariate objective function along
      `n` distinct directions at once) accepting n points as input, i.e. a
      tensor of shape [n], and the fields 'x', 'f' and 'df' in the returned
      namedtuple should each be a tensor of shape [n], with the corresponding
      input points, function values, and derivatives at those input points.
    init_interval: Instance of `HagerZhangLineSearchResults` containing
      the initial line search interval. The gradient of init_interval.left must
      be negative (i.e. must be a descent direction), while init_interval.right
      must be positive and finite.
    f_lim: Scalar `Tensor` of float dtype.
    max_iterations: Positive scalar `Tensor` of integral dtype. The maximum
      number of iterations to perform in the line search. The number of
      iterations used to bracket the minimum are also counted against this
      parameter.
    shrinkage_param: Scalar positive Tensor of real dtype. Must be less than
      `1.`. Corresponds to the parameter `gamma` in [Hager and Zhang (2006)][2].
    expansion_param: Scalar positive `Tensor` of real dtype. Must be greater
      than `1.`. Used to expand the initial interval in case it does not bracket
      a minimum. Corresponds to `rho` in [Hager and Zhang (2006)][2].
    sufficient_decrease_param: Positive scalar `Tensor` of real dtype.
      Bounded above by the curvature param. Corresponds to `delta` in the
      terminology of [Hager and Zhang (2006)][2].
    curvature_param: Positive scalar `Tensor` of real dtype. Bounded above
      by `1.`. Corresponds to 'sigma' in the terminology of
      [Hager and Zhang (2006)][2].

  Returns:
    A namedtuple containing the following fields.
      converged: Boolean `Tensor` of shape [n]. Whether a point satisfying
        Wolfe/Approx wolfe was found.
      failed: Boolean `Tensor` of shape [n]. Whether line search failed e.g.
        if either the objective function or the gradient are not finite at
        an evaluation point.
      iterations: Scalar int32 `Tensor`. Number of line search iterations made.
      func_evals: Scalar int32 `Tensor`. Number of function evaluations made.
      left: A namedtuple, as returned by value_and_gradients_function,
        of the left end point of the updated bracketing interval.
      right: A namedtuple, as returned by value_and_gradients_function,
        of the right end point of the updated bracketing interval.
  """
  bracket_result = hzl.bracket(value_and_gradients_function, init_interval,
                               f_lim, max_iterations, expansion_param)

  converged = init_interval.converged | _very_close(
      bracket_result.left.x, bracket_result.right.x)

  # We fail if we have not yet converged but already exhausted all iterations.
  exhausted_iterations = ~converged & tf.greater_equal(
      bracket_result.iteration, max_iterations)

  line_search_args = HagerZhangLineSearchResult(
      converged=converged,
      failed=bracket_result.failed | exhausted_iterations,
      iterations=bracket_result.iteration,
      func_evals=bracket_result.num_evals,
      left=bracket_result.left,
      right=bracket_result.right)

  return _line_search_after_bracketing(
      value_and_gradients_function, line_search_args, init_interval.left,
      f_lim, max_iterations, sufficient_decrease_param, curvature_param,
      shrinkage_param)


def _line_search_after_bracketing(
    value_and_gradients_function,
    search_interval,
    val_0,
    f_lim,
    max_iterations,
    sufficient_decrease_param,
    curvature_param,
    shrinkage_param):
  """The main loop of line search after the minimum has been bracketed.

  Args:
    value_and_gradients_function: A Python callable that accepts a real scalar
      tensor and returns a namedtuple with the fields 'x', 'f', and 'df' that
      correspond to scalar tensors of real dtype containing the point at which
      the function was evaluated, the value of the function, and its
      derivative at that point. The other namedtuple fields, if present,
      should be tensors or sequences (possibly nested) of tensors.
      In usual optimization application, this function would be generated by
      projecting the multivariate objective function along some specific
      direction. The direction is determined by some other procedure but should
      be a descent direction (i.e. the derivative of the projected univariate
      function must be negative at 0.).
      Alternatively, the function may represent the batching of `n` such line
      functions (e.g. projecting a single multivariate objective function along
      `n` distinct directions at once) accepting n points as input, i.e. a
      tensor of shape [n], and the fields 'x', 'f' and 'df' in the returned
      namedtuple should each be a tensor of shape [n], with the corresponding
      input points, function values, and derivatives at those input points.
    search_interval: Instance of `HagerZhangLineSearchResults` containing
      the current line search interval.
    val_0: A namedtuple as returned by value_and_gradients_function evaluated
      at `0.`. The gradient must be negative (i.e. must be a descent direction).
    f_lim: Scalar `Tensor` of float dtype.
    max_iterations: Positive scalar `Tensor` of integral dtype. The maximum
      number of iterations to perform in the line search. The number of
      iterations used to bracket the minimum are also counted against this
      parameter.
    sufficient_decrease_param: Positive scalar `Tensor` of real dtype.
      Bounded above by the curvature param. Corresponds to `delta` in the
      terminology of [Hager and Zhang (2006)][2].
    curvature_param: Positive scalar `Tensor` of real dtype. Bounded above
      by `1.`. Corresponds to 'sigma' in the terminology of
      [Hager and Zhang (2006)][2].
    shrinkage_param: Scalar positive Tensor of real dtype. Must be less than
      `1.`. Corresponds to the parameter `gamma` in [Hager and Zhang (2006)][2].

  Returns:
    A namedtuple containing the following fields.
      converged: Boolean `Tensor` of shape [n]. Whether a point satisfying
        Wolfe/Approx wolfe was found.
      failed: Boolean `Tensor` of shape [n]. Whether line search failed e.g.
        if either the objective function or the gradient are not finite at
        an evaluation point.
      iterations: Scalar int32 `Tensor`. Number of line search iterations made.
      func_evals: Scalar int32 `Tensor`. Number of function evaluations made.
      left: A namedtuple, as returned by value_and_gradients_function,
        of the left end point of the updated bracketing interval.
      right: A namedtuple, as returned by value_and_gradients_function,
        of the right end point of the updated bracketing interval.
  """

  def _loop_cond(curr_interval):
    """Loop condition."""
    active = ~(curr_interval.converged | curr_interval.failed)
    return (curr_interval.iterations <
            max_iterations) & tf.reduce_any(input_tensor=active)

  def _loop_body(curr_interval):
    """The loop body."""
    secant2_raw_result = hzl.secant2(
        value_and_gradients_function, val_0, curr_interval, f_lim,
        sufficient_decrease_param, curvature_param)
    secant2_result = HagerZhangLineSearchResult(
        converged=secant2_raw_result.converged,
        failed=secant2_raw_result.failed,
        iterations=curr_interval.iterations + 1,
        func_evals=secant2_raw_result.num_evals,
        left=secant2_raw_result.left,
        right=secant2_raw_result.right)

    should_check_shrinkage = ~(secant2_result.converged | secant2_result.failed)

    def _do_check_shrinkage():
      """Check if interval has shrinked enough."""
      old_width = curr_interval.right.x - curr_interval.left.x
      new_width = secant2_result.right.x - secant2_result.left.x
      sufficient_shrinkage = new_width < old_width * shrinkage_param
      func_is_flat = (
          _very_close(curr_interval.left.f, curr_interval.right.f) &
          _very_close(secant2_result.left.f, secant2_result.right.f))

      new_converged = (
          should_check_shrinkage & sufficient_shrinkage & func_is_flat)
      needs_inner_bisect = should_check_shrinkage & ~sufficient_shrinkage

      inner_bisect_args = secant2_result._replace(
          converged=secant2_result.converged | new_converged)

      def _apply_inner_bisect():
        return _line_search_inner_bisection(
            value_and_gradients_function, inner_bisect_args,
            needs_inner_bisect, f_lim)

      return prefer_static.cond(
          tf.reduce_any(input_tensor=needs_inner_bisect),
          _apply_inner_bisect,
          lambda: inner_bisect_args)

    next_args = prefer_static.cond(
        tf.reduce_any(input_tensor=should_check_shrinkage),
        _do_check_shrinkage,
        lambda: secant2_result)

    interval_shrunk = (
        ~next_args.failed & _very_close(next_args.left.x, next_args.right.x))
    return [next_args._replace(converged=next_args.converged | interval_shrunk)]

  return tf.while_loop(
      cond=_loop_cond,
      body=_loop_body,
      loop_vars=[search_interval],
      parallel_iterations=1)[0]


def _line_search_inner_bisection(
    value_and_gradients_function,
    search_interval,
    active,
    f_lim):
  """Performs bisection and updates the interval."""
  midpoint = (search_interval.left.x + search_interval.right.x) / 2
  val_mid = value_and_gradients_function(midpoint)
  is_valid_mid = hzl.is_finite(val_mid)

  still_active = active & is_valid_mid
  new_failed = active & ~is_valid_mid
  next_inteval = search_interval._replace(
      failed=search_interval.failed | new_failed,
      func_evals=search_interval.func_evals + 1)

  def _apply_update():
    update_result = hzl.update(
        value_and_gradients_function, next_inteval.left, next_inteval.right,
        val_mid, f_lim, active=still_active)
    return HagerZhangLineSearchResult(
        converged=next_inteval.converged,
        failed=next_inteval.failed | update_result.failed,
        iterations=next_inteval.iterations + update_result.iteration,
        func_evals=next_inteval.func_evals + update_result.num_evals,
        left=update_result.left,
        right=update_result.right)

  return prefer_static.cond(
      tf.reduce_any(input_tensor=still_active),
      _apply_update,
      lambda: next_inteval)


def _prepare_args(value_and_gradients_function,
                  initial_step_size,
                  val_initial,
                  val_0,
                  approximate_wolfe_threshold):
  """Prepares the arguments for the line search initialization.

  Args:
    value_and_gradients_function: A Python callable that accepts a real scalar
      tensor and returns a namedtuple with the fields 'x', 'f', and 'df' that
      correspond to scalar tensors of real dtype containing the point at which
      the function was evaluated, the value of the function, and its
      derivative at that point. The other namedtuple fields, if present,
      should be tensors or sequences (possibly nested) of tensors.
      In usual optimization application, this function would be generated by
      projecting the multivariate objective function along some specific
      direction. The direction is determined by some other procedure but should
      be a descent direction (i.e. the derivative of the projected univariate
      function must be negative at 0.).
      Alternatively, the function may represent the batching of `n` such line
      functions (e.g. projecting a single multivariate objective function along
      `n` distinct directions at once) accepting n points as input, i.e. a
      tensor of shape [n], and the fields 'x', 'f' and 'df' in the returned
      namedtuple should each be a tensor of shape [n], with the corresponding
      input points, function values, and derivatives at those input points.
    initial_step_size: Scalar positive `Tensor` of real dtype, or a tensor of
      shape [n] in batching mode. The initial value (or values) to try to
      bracket the minimum. Default is `1.` as a float32.
      Note that this point need not necessarily bracket the minimum for the line
      search to work correctly but the supplied value must be greater than 0.
      A good initial value will make the search converge faster.
    val_initial: The full return value of evaluating
      value_and_gradients_function at initial_step_size, i.e. a namedtuple with
      'x', 'f', 'df', if already known by the caller. If not None the value of
      `initial_step_size` will be ignored, otherwise the tuple will be computed
      by evaluating value_and_gradients_function.
    val_0: The full return value of value_and_gradients_function at `0.`, i.e.
      a namedtuple with 'x', 'f', 'df', if already known by the caller. If None
      the tuple will be computed by evaluating value_and_gradients_function.
    approximate_wolfe_threshold: Scalar positive `Tensor` of
      real dtype. Corresponds to the parameter 'epsilon' in
      [Hager and Zhang (2006)][2]. Used to estimate the
      threshold at which the line search switches to approximate Wolfe
      conditions.

  Returns:
    left: A namedtuple, as returned by value_and_gradients_function,
      containing the value and derivative of the function at `0.`.
    val_initial: A namedtuple, as returned by value_and_gradients_function,
      containing the value and derivative of the function at
      `initial_step_size`.
    f_lim: Real `Tensor` of shape [n]. The function value threshold for
      the approximate Wolfe conditions to be checked.
    eval_count: Scalar int32 `Tensor`. The number of target function
      evaluations made by this function.
  """
  eval_count = 0
  if val_initial is None:
    if initial_step_size is not None:
      initial_step_size = tf.convert_to_tensor(value=initial_step_size)
    else:
      initial_step_size = tf.convert_to_tensor(value=1.0, dtype=tf.float32)
    val_initial = value_and_gradients_function(initial_step_size)
    eval_count += 1

  if val_0 is None:
    x_0 = tf.zeros_like(val_initial.x)
    val_0 = value_and_gradients_function(x_0)
    eval_count += 1

  f_lim = val_0.f + (approximate_wolfe_threshold * tf.abs(val_0.f))
  return val_0, val_initial, f_lim, tf.convert_to_tensor(value=eval_count)


def _very_close(x, y):
  return tf.math.nextafter(x, y) >= y


def _to_str(x):
  """Converts a bool tensor to a string with True/False values."""
  x = tf.convert_to_tensor(value=x)
  if x.dtype == tf.bool:
    return tf.compat.v1.where(x, tf.fill(x.shape, 'True'),
                              tf.fill(x.shape, 'False'))
  return x


# A convenience function useful while debugging in the graph mode.
def _print(pass_through_tensor, values):
  """Wrapper for tf.Print which supports lists and namedtuples for printing."""
  flat_values = []
  for value in values:
    # Checks if it is a namedtuple.
    if hasattr(value, '_fields'):
      for field in value._fields:
        flat_values.extend([field, _to_str(getattr(value, field))])
      continue
    if isinstance(value, (list, tuple)):
      for v in value:
        flat_values.append(_to_str(v))
      continue
    flat_values.append(_to_str(value))
  return tf.compat.v1.Print(pass_through_tensor, flat_values)
