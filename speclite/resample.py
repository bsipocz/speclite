# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""Resample spectra using interpolation.
"""
from __future__ import print_function, division

import collections
import numpy as np
import numpy.ma as ma
import scipy.interpolate

import speclite.utility


def resample_array(x_in, x_out, y_in, y_out=None, kind='linear', axis=-1,
                   name='y'):
    """Resample a single array.

    The inputs specify a function y(x) tabulated at discrete values x=x_in.
    The output is an interpolated estimate of y(x) at x=x_out.

    The :func:`resample` function provides a convenient wrapper for resampling
    each column of a tabular object like a numpy structured array or an
    astropy table.

    The x_in and x_out parameters are passed directly to
    :func:`scipy.interpolate.interp1d` and must be convertible to numpy arrays.
    Use the :func:`resample` wrapper if these parameters have units.

    Parameters
    ----------
    x_in : array
        Array of input x values corresponding to each y_in value along the
        specified axis.
    x_out : array
        Array of output x values corresponding to each y_out value along the
        specified axis.
    y_in : array
        Array of input y values to resample.  Must have the same size along
        the specified axis as x_in.  Values must be numeric and finite (but
        invalid values can be masked).
    y_out : numpy array or None
        Array where output values should be written.  If None is specified
        an appropriate array will be created. If y_out is the same object
        as y_in, the resampling transform is performed in place.
    kind : string or integer
        Specify the kind of interpolation models to build using any of the
        forms allowed by :class:`scipy.interpolate.inter1pd`.  If y_in is
        masked, only the ``nearest` and ``linear`` values are allowed.
    axis : int
        Axis of y_in that will be used for resampling.
    name : str
        Name associated with y to include in any exception message.

    Returns
    -------
    numpy array
        An array of y(x) values resampled to x=x_out.  The array will have
        the same data type as y_in and will have a size along the specified
        axis that matches the size of x_out.
    """
    y_in = np.asanyarray(y_in)
    if not np.issubdtype(y_in.dtype, np.number):
        raise ValueError(
            'Cannot resample non-numeric values for {0}.'.format(name))
    if not np.all(np.isfinite(y_in)):
        raise ValueError(
            'Cannot resample non-finite values for {0}.'.format(name))

    if y_in.shape[axis] != len(x_in):
        raise ValueError('Input shape of {0} cannot be resampled: {1}.'
                         .format(name, y_in.shape))

    # Calculate the output shape.
    y_out_shape = list(y_in.shape)
    y_out_shape[axis] = len(x_out)

    # The output must be masked if any extrapolation is required.
    if np.min(x_out) < np.min(x_in) or np.max(x_out) > np.max(x_in):
        add_mask = True
    else:
        add_mask = False

    if y_out is not None:
        #y_out = speclite.utility.validate_array(name, )
        if (ma.isMaskedArray(y_in) or add_mask) and not ma.isMaskedArray(y_out):
            raise ValueError('Output {0} must be masked.'.format(name))
        if y_out.shape != y_out_shape:
            raise ValueError('Invalid output shape {0} for {1}.'
                             .format(y_out.shape, name))
        if y_out.dtype != y_in.dtype:
            raise ValueError('Invalid output dtype {0} for {1}.'
                             .format(y_out.dtype, name))
    else:
        y_out = speclite.utility.empty_like(
            y_in, y_out_shape, y_in.dtype, add_mask)

    # Convert masked y_in values to NaN. This converts a numpy MaskedArray to
    # a regular array and a MaskedColumn to regular Column.
    if ma.isMaskedArray(y_in):
        y_in = y_in.filled(np.nan)

    # Remove any units before interpolation.  This replaces a Quantity or
    # a Column with a regular numpy array.
    try:
        y_unit = y_in.unit
        if hasattr(y_in, 'value'):
            # Convert a Quantity to a numpy array.
            y_in = y_in.value
        elif hasattr(y_in, 'data'):
            # Convert a Column to a numpy array.
            y_in = y_in.data
        else:
            raise ValueError('Unsupported type {0} for {1}.'
                             .format(type(y_in), name))
    except AttributeError:
        # y_in has no units.
        y_unit = 1

    # interp1d will only propagate NaNs correctly for certain values of `kind`.
    # With numpy = 1.6 or 1.7, only 'nearest' and 'linear' work.
    # With numpy = 1.8 or 1.9, 'slinear' and kind = 0 or 1 also work.
    if np.any(np.isnan(y_in)):
        if kind not in ('nearest', 'linear'):
            raise ValueError(
                'Interpolation kind not supported for masked data: {0}.'
                .format(kind))

    try:
        # Do the interpolation using NaN for any extrapolated values.
        interpolator = scipy.interpolate.interp1d(
            x_in, y_in, kind=kind, axis=axis, copy=False,
            bounds_error=False, fill_value=np.nan)
        y_out[:] = interpolator(x_out) * y_unit

    except NotImplementedError:
        raise ValueError('Interpolation kind not supported: {0}.'.format(kind))

    # Mask any NaN values if the output is masked.
    if ma.isMaskedArray(y_out):
        y_out.mask = np.isnan(y_out.data)

    return y_out


def resample(data_in, x_in, x_out, y, data_out=None, kind='linear', axis=-1):
    """Resample the columns of a tabular object.

    Uses :function:`resample_array`.
    """
    # Convert the input data into a dictionary of read-only arrays.
    arrays_in, _ = speclite.utility.prepare_data(
        'read_only', args=[data_in], kwargs={})

    if data_out is not None:
        # Convert the output data into a dictionary of writable arrays.
        arrays_out, return_value = speclite.utility.prepare_data(
            'in_place', args=[data_out], kwargs={})
    else:
        arrays_out = collections.OrderedDict()
        return_value = None

    # x_in can either be the name of an input array or an array itself.
    # Set x_out_name to the name to use for x_out in the output, if any.
    if isinstance(x_in, basestring):
        if x_in not in arrays_in:
            raise ValueError('No such x_in field: {0}.'.format(x_in))
        x_out_name = x_in
        x_in = arrays_in[x_in]
    else:
        x_in = np.asanyarray(x_in)
        x_out_name = None

    # x_in must be a 1D array of un-masked floating-point values.
    if len(x_in.shape) != 1:
        raise ValueError('x_in must be a 1D array.')
    if not np.issubdtype(x_in.dtype, np.number):
        raise ValueError('x_in must be an array of floating point values.')
    if ma.isMA(x_in) and np.any(x_in.mask):
        raise ValueError('Cannot resample from masked x_in.')

    # x_out must be a 1D array of un-masked floating-point values.
    x_out = np.asanyarray(x_out)
    if len(x_out.shape) != 1:
        raise ValueError('x_out must be a 1D array.')
    if not np.issubdtype(x_out.dtype, np.number):
        raise ValueError('x_out must be an array of floating point values.')
    if ma.isMA(x_out) and np.any(x_out.mask):
        raise ValueError('Cannot resample to masked x_out.')

    # Handle optional units for x_in, x_out
    pass

    # Process the list of array names to resample.
    y_names = speclite.utility.validate_selected_names(y, arrays_in.keys())

    if x_out_name is not None:
        if data_out is None:
            # Add an array of x_out values.  Note that this will always be
            # the first column in a tabular result, independent of the
            # position of of the original x_in column.
            x_out_array = speclite.utility.empty_like(
                x_in, x_out.shape, x_out.dtype)
            x_out_array[:] = x_out
            arrays_out[x_out_name] = x_out_array
        else:
            if x_out_name not in arrays_out:
                raise ValueError('data_out missing required column {0}.'
                                 .format(x_out_name))
            arrays_out[x_out_name][:] = x_out

    for name in arrays_in:
        # Only resample arrays named in y.
        if name not in y:
            continue
        if data_out is not None:
            if name not in arrays_out:
                raise ValueError('data_out missing required column {0}.'
                                 .format(name))
            y_out = arrays_out[name]
        else:
            y_out = None
        arrays_out[name] = resample_array(
            x_in, x_out, arrays_in[name], y_out, kind, axis, name)

    if return_value is None:
        return_value = speclite.utility.tabular_like(data_in, arrays_out)

    return return_value


def resample_orig(data_in, x_in, x_out, y, data_out=None, kind='linear'):
    """Resample the data of one spectrum using interpolation.

    Dependent variables y1, y2, ... in the input data are resampled in the
    independent variable x using interpolation models y1(x), y2(x), ...
    evaluated on a new grid of x values. The independent variable will
    typically be a wavelength or frequency and the independent variables can
    be fluxes, inverse variances, etc.

    Interpolation is intended for cases where the input and output grids have
    comparable densities. When neighboring samples are correlated, the
    resampling process should be essentially lossless.  When the output
    grid is sparser than the input grid, it may be more appropriate to
    "downsample", i.e., average dependent variables over consecutive ranges
    of input samples.

    The basic usage of this function is:

    >>> data = np.ones((5,),
    ... [('wlen', float), ('flux', float), ('ivar', float)])
    >>> data['wlen'] = np.arange(4000, 5000, 200)
    >>> wlen_out = np.arange(4100, 4700, 200)
    >>> resample(data, 'wlen', wlen_out, ('flux', 'ivar'))
    array([(4100, 1.0, 1.0), (4300, 1.0, 1.0), (4500, 1.0, 1.0)],
          dtype=[('wlen', '<i8'), ('flux', '<f8'), ('ivar', '<f8')])

    The input grid can also be external to the structured array of spectral
    data, for example:

    >>> data = np.ones((5,), [('flux', float), ('ivar', float)])
    >>> wlen_in = np.arange(4000, 5000, 200)
    >>> wlen_out = np.arange(4100, 4900, 200)
    >>> resample(data, wlen_in, wlen_out, ('flux', 'ivar'))
    array([(1.0, 1.0), (1.0, 1.0), (1.0, 1.0), (1.0, 1.0)],
          dtype=[('flux', '<f8'), ('ivar', '<f8')])

    If the output grid extends beyond the input grid, a `masked array
    <http://docs.scipy.org/doc/numpy/reference/maskedarray.html>`__ will be
    returned with any values requiring extrapolation masked:

    >>> wlen_out = np.arange(3500, 5500, 500)
    >>> resample(data, wlen_in, wlen_out, 'flux')
    masked_array(data = [(--,) (1.0,) (1.0,) (--,)],
                 mask = [(True,) (False,) (False,) (True,)],
           fill_value = (1e+20,),
                dtype = [('flux', '<f8')])

    If the input data is masked, any output interpolated values that depend on
    an input masked value will be masked in the output:

    >>> data = ma.ones((5,), [('flux', float), ('ivar', float)])
    >>> data['flux'][2] = ma.masked
    >>> wlen_out = np.arange(4100, 4900, 200)
    >>> resample(data, wlen_in, wlen_out, 'flux')
    masked_array(data = [(1.0,) (--,) (--,) (1.0,)],
                 mask = [(False,) (True,) (True,) (False,)],
           fill_value = (1e+20,),
                dtype = [('flux', '<f8')])

    Interpolation is performed using :class:`scipy.interpolate.inter1pd`.

    Parameters
    ----------
    data_in : numpy.ndarray or numpy.ma.MaskedArray
        Structured numpy array of input spectral data to resample. The input
        array must be one-dimensional.
    x_in : string or numpy.ndarray
        A field name in data_in containing the independent variable to use
        for interpolation, or else an array of values with the same shape
        as the input data.
    x_out : numpy.ndarray
        An array of values for the independent variable where interpolation
        models should be evaluated to calculate the output values.
    y : string or iterable of strings.
        A field name or a list of field names present in the input data that
        should be resampled by interpolation and included in the output.
    data_out : numpy.ndarray or None
        Structured numpy array where the output result should be written. If
        None is specified, then an appropriately sized array will be allocated
        and returned. Use this method to take control of the memory allocation
        and, for example, re-use the same array when resampling many spectra.
    kind : string or integer
        Specify the kind of interpolation models to build using any of the
        forms allowed by :class:`scipy.interpolate.inter1pd`.  If any input
        dependent values are masked, only the ``nearest` and ``linear``
        values are allowed.

    Returns
    -------
    numpy.ndarray or numpy.ma.MaskedArray
        Structured numpy array of the resampled result containing all ``y``
        fields and (if ``x_in`` is specified as a string) the output ``x``
        field.  The output will be a :class:`numpy.ma.MaskedArray` if ``x_out``
        extends beyond ``x_in`` or if ``data_in`` is masked.
    """
    if not isinstance(data_in, np.ndarray):
        raise ValueError('Invalid data_in type: {0}.'.format(type(data_in)))
    if data_in.dtype.fields is None:
        raise ValueError('Input data_in is not a structured array.')
    if len(data_in.shape) > 1:
        raise ValueError('Input data_in is multidimensional.')

    if isinstance(x_in, basestring):
        if x_in not in data_in.dtype.names:
            raise ValueError('No such x_in field: {0}.'.format(x_in))
        x_out_name = x_in
        x_in = data_in[x_in]
    else:
        if not isinstance(x_in, np.ndarray):
            raise ValueError('Invalid x_in type: {0}.'.format(type(x_in)))
        if x_in.shape != data_in.shape:
            raise ValueError('Incompatible shapes for x_in and data_in.')
        x_out_name = None

    if not isinstance(x_out, np.ndarray):
        raise ValueError('Invalid x_out type: {0}.'.format(type(data_out)))

    if ma.isMA(x_in) and np.any(x_in.mask):
        raise ValueError('Cannot resample masked x_in.')

    x_type = np.promote_types(x_in.dtype, x_out.dtype)

    dtype_out = []
    if x_out_name is not None:
        dtype_out.append((x_out_name, x_out.dtype))

    if isinstance(y, basestring):
        # Use a list instead of a tuple here so y_names can be used
        # to index data_in below.
        y_names = [y,]
    else:
        try:
            y_names = [name for name in y]
        except TypeError:
            raise ValueError('Invalid y type: {0}.'.format(type(y)))
    for not_first, y in enumerate(y_names):
        if y not in data_in.dtype.names:
            raise ValueError('No such y field: {0}.'.format(y))
        if not_first:
            if data_in[y].dtype != y_type:
                raise ValueError('All y fields must have the same type.')
        else:
            y_type = data_in[y].dtype
        dtype_out.append((y, y_type))

    y_shape = (len(y_names),)
    if ma.isMA(data_in):
        # Copy the structured 1D array into a 2D unstructured array
        # and set masked values to NaN.
        y_in = np.zeros(data_in.shape + y_shape, y_type)
        for i,y in enumerate(y_names):
            y_in[:,i] = data_in[y].filled(np.nan)
    else:
        y_in = data_in[y_names]
        # View the structured 1D array as a 2D unstructured array (without
        # copying any memory).
        y_in = y_in.view(y_type).reshape(data_in.shape + y_shape)
    # interp1d will only propagate NaNs correctly for certain values of `kind`.
    # With numpy = 1.6 or 1.7, only 'nearest' and 'linear' work.
    # With numpy = 1.8 or 1.9, 'slinear' and kind = 0 or 1 also work.
    if np.any(np.isnan(y_in)):
        if kind not in ('nearest', 'linear'):
            raise ValueError(
                'Interpolation kind not supported for masked data: {0}.'
                .format(kind))
    try:
        interpolator = scipy.interpolate.interp1d(
            x_in, y_in, kind=kind, axis=0, copy=False,
            bounds_error=False, fill_value=np.nan)
    except NotImplementedError:
        raise ValueError('Interpolation kind not supported: {0}.'.format(kind))

    shape_out = (len(x_out),)
    if data_out is None:
        data_out = np.empty(shape_out, dtype_out)
    else:
        if data_out.shape != shape_out:
            raise ValueError(
                'data_out has wrong shape: {0}. Expected: {1}.'
                .format(data_out.shape, shape_out))
        if data_out.dtype != dtype_out:
            raise ValueError(
                'data_out has wrong dtype: {0}. Expected: {1}.'
                .format(data_out.dtype, dtype_out))

    if x_out_name is not None:
        data_out[x_out_name][:] = x_out
    y_out = interpolator(x_out)
    for i,y in enumerate(y_names):
        data_out[y][:] = y_out[:,i]

    if ma.isMA(data_in) or np.any(np.isnan(y_out)):
        data_out = ma.MaskedArray(data_out)
        data_out.mask = False
        for y in y_names:
            data_out[y].mask = np.isnan(data_out[y].data)

    return data_out
