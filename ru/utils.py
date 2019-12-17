import logging
from collections import namedtuple, defaultdict
from pathlib import Path
from random import random
import numpy as np
import toml
from operator import itemgetter
import requests
import json

from ru.channels import MINION_CHANNELS, FLONGLE_CHANNELS


def execute_command_as_string(data, host=None, port=None):
    """"""
    r = requests.post(
        "http://{}:{}/jsonrpc".format(host, port),
        data=data,
        headers={"Content-Length": str(len(data)), "Content-Type": "application/json"},
    )
    try:
        json_respond = json.loads(r.text)
        return json_respond
    except Exception as err:
        # FIXME: raise
        print(err)


def send_message_port(message, ip_address, port):
    message_to_send = (
            '{"id":"1", "severity": "2", "method":"user_message","params":{"content":"%s"}}' % message
    )
    results = ""
    try:
        results = execute_command_as_string(message_to_send, ip_address, port)
    except Exception as err:
        # FIXME: raise
        print("message send fail", err)
    return results

def sendmessage(rpc_connection,severitylevel,message):
    rpc_connection.log.send_user_message(severity=severitylevel, user_message=message)


def dynamic_import(name):
    """Dynamically import modules and classes, used to get the ReadCache

    https://stackoverflow.com/a/547867/3279716
    https://docs.python.org/2.4/lib/built-in-funcs.html

    Parameters
    ----------
    name : str
        The module/class path. E.g: "read_until.read_cache.{}".format("ReadCache")

    Returns
    -------
    module
    """
    components = name.split('.')
    mod = __import__(components[0])
    for comp in components[1:]:
        mod = getattr(mod, comp)
    return mod


def named_tuple_generator(dictionary, name='Conditions',):
    """Generate named tuple from dictionary

    Parameters
    ----------
    dictionary : dict
        dict to turn into a named tuple
    name : str
        The name to give the named tuple

    Returns
    -------
    namedtuple
    """
    return namedtuple(name, dictionary.keys())(**dictionary)


def nice_join(seq, sep=", ", conjunction="or"):
    """Join lists nicely"""
    seq = [str(x) for x in seq]

    if len(seq) <= 1 or conjunction is None:
        return sep.join(seq)
    else:
        return "{} {} {}".format(sep.join(seq[:-1]), conjunction, seq[-1])


def get_log_level(s):
    """Get log level from logging"""
    return getattr(logging, s.upper())


def read_lines_to_list(f):
    """Read file to list and return the list"""
    with open(f) as fh:
        lines = [line.strip() for line in fh]
    return lines


def print_args(args, logger=None, exclude=None):
    """Print and format all arguments from the command line"""
    if exclude is None:
        exclude = []
    dirs = dir(args)
    m = max([len(a) for a in dirs if a[0] != '_'])
    for attr in dirs:
        if attr[0] != '_' and attr not in exclude and attr.lower() == attr:
            if logger is not None:
                logger.info("{a}={b}".format(a=attr, m=m, b=getattr(args, attr)))
            else:
                print('{a:<{m}}\t{b}'.format(a=attr, m=m, b=getattr(args, attr)))


def get_coords(channel, flowcell_size):
    """Return a channel's coordinates given a flowcell size

    Parameters
    ----------
    channel : int
        The channel to retrieve the coordinates for
    flowcell_size : int
        The flowcell size, this is used to determine the flowcell layout

    Returns
    -------
    tuple
        Tuple of int: (column, row)

    Raises
    ------
    ValueError
        Raised if channel outside of bounds (0, flowcell_size)
        Raised if flowcell_size not one of [128, 512, 3000]
    """
    if channel <= 0 or channel > flowcell_size:
        raise ValueError("channel cannot be below 0 or above flowcell_size")

    if flowcell_size == 3000:
        # find which block of 12 we are in:
        block = (channel - 1) // 250
        remainder = (channel - 1) % 250
        row = remainder // 10
        column = remainder % 10 + block * 10
        return column, row
    elif flowcell_size == 126:
        return FLONGLE_CHANNELS[channel]
    elif flowcell_size == 512:
        return MINION_CHANNELS[channel]
    else:
        raise ValueError("flowcell_size is not recognised")


def get_flowcell_array(flowcell_size):
    """Return a numpy.ndarray in the shape of a flowcell

    Parameters
    ----------
    flowcell_size : int
        The total number of channels on the flowcell; 126 for Flongle, 512
        for MinION, and 3000 for PromethION

    Returns
    -------
    np.ndarray
        An N-dimensional array representation of the flowcell

    Examples
    --------
    >>> get_flowcell_array(126).shape
    (10, 13)
    >>> get_flowcell_array(512).shape
    (16, 32)
    >>> get_flowcell_array(3000).shape
    (25, 120)
    >>> get_flowcell_array(128)
    Traceback (most recent call last):
        ...
    ValueError: flowcell_size is not recognised
    >>> get_flowcell_array(126)[9][-1]
    0
    >>> get_flowcell_array(512)[15][-1]
    1

    """
    # Make a list of tuples of (column, row, channel)
    coords = [(*get_coords(x, flowcell_size), x) for x in range(1, flowcell_size + 1)]

    # Initialise a nd array using the max row and column from coords
    b = np.zeros(
        (
            max(coords, key=itemgetter(1))[1] + 1,
            max(coords, key=itemgetter(0))[0] + 1
        ),
        dtype=int
    )

    # Mimic flowcell layout in an array
    for col, row, chan in coords:
        b[row][col] += chan

    # return the reversed array, to get the right orientation
    return b[::-1]


def generate_flowcell(flowcell_size, split=1, axis=1, odd_even=False):
    """Return an list of lists with channels to use in conditions

    Representations generated by this method are evenly split based on the physical
    layout of the flowcell. Each sub-list is the same size. Axis determines whether
    the flowcell divisions will go left-right (0) or top-bottom (1); as flongle has
    a shape of (10, 13) the top-bottom axis cannot be split evenly.

    Parameters
    ----------
    flowcell_size : int
        The total number of channels on the flowcell; 126 for Flongle, 512 for MinION,
        and 3000 for PromethION
    split : int
        The number of sections to split the flowcell into, must be a positive factor
        of the flowcell dimension
    axis : int, optional
        The axis along which to split,
        see: https://docs.scipy.org/doc/numpy/glossary.html?highlight=axis
    odd_even : bool
        Return a list of two lists split into odd-even channels,
        ignores `split` and `axis`

    Returns
    -------
    list
        A list of lists with channels divided equally

    Raises
    ------
    ValueError
        Raised when split is not a positive integer
        Raised when the value for split is not a factor on the axis provided

    Examples
    --------
    >>> len(generate_flowcell(512))
    1
    >>> len(generate_flowcell(512)[0])
    512
    >>> len(generate_flowcell(512, split=4))
    4
    >>> for x in generate_flowcell(512, split=4):
    ...     print(len(x))
    128
    128
    128
    128
    >>> generate_flowcell(512, split=5)
    Traceback (most recent call last):
        ...
    ValueError: The flowcell cannot be split evenly
    """
    if odd_even:
        return [
            list(range(1, flowcell_size + 1, 2)),
            list(range(2, flowcell_size + 1, 2)),
        ]

    arr = get_flowcell_array(flowcell_size)

    if split <= 0:
        raise ValueError("split must be a positive integer")

    try:
        arr = np.array(np.split(arr, split, axis=axis))
    except ValueError:
        # The number of targets cannot be split evenly over the flowcell.
        #   For MinION flowcells the number of targets must be a factor of 16 or
        #   32 for axis 0 or 1 respectively; for PromethION flowcells the number
        #   of targets must be a factor of 25 or 120 for axis 0 or 1 respectively.
        raise ValueError("The flowcell cannot be split evenly")

    arr.shape = (arr.shape[0], arr.shape[1] * arr.shape[2])
    return [x for x in arr.tolist()]


def get_targets(targets):
    """

    Parameters
    ----------
    targets : str or List[str]

    Returns
    -------
    defaultdict of list
    {
        'strand':
            {
                'contig': [(int, int), ...]
            }
    }
    """
    t = defaultdict(lambda: defaultdict(list))
    if isinstance(targets, str):
        # Load from list
        if Path(targets).is_file():
            targets = read_lines_to_list(targets)
        # If targets is not a file, then raise error

    for item in targets:
        ctg, *coords = item.split(",")
        if coords:
            strand = coords.pop()
            t[strand][ctg].append(tuple(int(x) for x in coords))
        else:
            for strand in ["+", "-"]:
                t[strand][ctg].append((0, float("inf")))

    return t


def get_run_info(toml_dict_or_filepath, num_channels=512):
    """Convert a TOML representation of a Read Until experiment to conditions that
    can be used used by the analysis function

    Parameters
    ----------
    toml_dict_or_filepath : dict or str
        Dictionary from a TOML file or a path (str) to a TOML file. If a str is given
        the file will be loaded using toml.load() Expected keys: 'conditions'
    num_channels : int
        Total number of channels on the sequencer, expects 512 for MinION and 3000 for
        PromethION

    Returns
    -------
    run_info : dict
        dict with a key per channel, the value maps to an index in `split_conditions`
    split_conditions : list
        List of namedtuples with conditions specified in the TOML file
    reference : str
        The path to the reference MMI file
    """
    if not isinstance(toml_dict_or_filepath, dict):
        toml_dict = toml.load(toml_dict_or_filepath)
    else:
        toml_dict = toml_dict_or_filepath

    # Get condition keys, these should be ascending integers
    conditions = [
        k for k in toml_dict["conditions"].keys()
        if isinstance(toml_dict["conditions"].get(k), dict)
    ]

    # If maintain_order, is True: condition keys are sorted -> [0, 1, 2, 3]
    #  else: sorted is used with random.random() to shuffle the keys -> [4, 1, 2, 3]
    #  this sort is applied during the creation of `split_conditions`
    #  If maintain_order is not provided, evaluates True -> sorted
    if toml_dict["conditions"].get("maintain_order", True):
        sort_func = lambda L: sorted(L)
    else:
        sort_func = lambda L: sorted(L, key=lambda k: random())

    # Generate the flowcell lists
    axis = toml_dict["conditions"].get("axis", 1)
    split_channels = generate_flowcell(num_channels, split=len(conditions), axis=axis)

    # convert targets to sets
    for k in conditions:
        cond = toml_dict["conditions"].get(k)
        if not isinstance(cond, dict):
            continue
        cond["coords"] = get_targets(cond["targets"])

        _t = []
        for _k in cond["coords"].keys():
            _t.extend(cond["coords"].get(_k).keys())

        cond["targets"] = set(_t)

    # Create a list of named tuples, these are the conditions
    split_conditions = [
        named_tuple_generator(toml_dict["conditions"].get(k))
        for k in sort_func(toml_dict["conditions"].keys())
        if isinstance(toml_dict["conditions"].get(k), dict)
    ]

    run_info = {
        channel: pos
        for pos, (channels, condition) in enumerate(
            zip(split_channels, split_conditions)
        )
        for channel in channels
    }

    reference = toml_dict["conditions"].get("reference")

    return run_info, split_conditions, reference


def between(pos, coords):
    """Return bool if position is between the coords

    Parameters
    ----------
    pos : int
        Position to check
    coords : tuple
        Region to check between

    Returns
    -------
    bool

    Examples
    --------

    Between can use any valid floats in the `coords` tuple

    >>> between(500, (0, float("inf")))
    True
    >>> between(5, (10, 100))
    False
    >>> any([between(5, (10, 100)), between(245000000, (0, float("inf"))), ])
    True
    >>> any([between(5, (10, 100)), between(-1, (0, float("inf"))), ])
    False

    """
    return min(coords) <= pos <= max(coords)


def setup_logger(name, log_format="%(message)s", log_file=None, level=logging.DEBUG):
    """Setup loggers

    Parameters
    ----------
    name : str
        Name to give the logger
    log_format : str
        logging format string using % formatting
    log_file : str
        File to record logs to, sys.stderr if not set
    level : logging.LEVEL
        Where logging.LEVEL is one of (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns
    -------
    logger
    """
    """Function setup as many loggers as you want"""
    formatter = logging.Formatter(log_format)
    if log_file is not None:
        handler = logging.FileHandler(log_file, mode="w")
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    return logger


if __name__ == "__main__":
    import doctest
    doctest.testmod()
