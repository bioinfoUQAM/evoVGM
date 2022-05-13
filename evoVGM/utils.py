from evoVGM.data import SeqCollection 

import time
import math
import platform
import importlib
from pprint import pformat

import torch

__author__ = "amine remita"


def timeSince(since):
    now = time.time()
    s = now - since
    m = math.floor(s / 60)
    s -= m * 60
    return '%dm %ds' % (m, s)

def get_categorical_prior(conf, prior_type, verbose=False):
    priors = []

    if prior_type in ["ancestor", "freqs"]:
        nb_categories = 4
    elif prior_type == "rates":
        nb_categories = 6
    else:
        raise ValueError(
                "prior type value should be ancestor, freqs or rates")

    if conf == "uniform":
        priors = torch.ones(nb_categories)/nb_categories
    elif "," in conf:
        priors = str2float_tensor(conf, ',', nb_categoriesi,
                prior_type)
    #elif conf == "empirical": # to be implemented
    #    pass
    else:
        raise ValueError(
                "Check {} prior config values".format(prior_type))

    if verbose:
        print("{} priors: {}".format(prior_type, priors))

    return priors

def get_branch_prior(conf, verbose=False):
    priors = str2float_tensor(conf, ",", 2, "branch")

    if verbose:
        print("Branch priors: {}".format(priors))
    
    return priors 

def str2float_tensor(chaine, sep, nb_values, prior_type):
    values = [float(v) for v in chaine.strip().split(sep)]
    if len(values) != nb_values:
        raise ValueError(
                "the Number of prior values for {} is not correct".format(prior_type))
    return torch.FloatTensor(values)

def str2ints(chaine, sep=","):
    return [int(s) for s in chaine.strip().split(sep)]

def str2floats(chaine, sep=","):
    return [float(s) for s in chaine.strip().split(sep)]

def fasta_to_list(fasta_file, verbose=False):
    # fetch sequences from fasta
    if verbose: print("Fetching sequences from {}".format(fasta_file))
    seqRec_list = SeqCollection.read_bio_file(fasta_file)
    return [str(seqRec.seq._data) for seqRec in seqRec_list] 

def str_to_list(chaine, sep=",", cast=None):
    c = lambda x: x
    if cast: c = cast

    return [c(i.strip()) for i in chaine.strip().split(sep)]

def str_to_values(chaine, nb_repeat=1, sep=",", cast=None):
    chaine = chaine.rstrip(sep)
    values = str_to_list(chaine, sep=sep, cast=cast)
    if len(values)==1 : values = values * nb_repeat

    return values

def write_conf_packages(args, out_file):

    with open(out_file, "wt") as f:
        f.write("\n# Program arguments\n# #################\n\n")
        args.write(f)

        f.write("\n# Package versions\n# ################\n\n")
        modules = pformat(get_modules_versions())
        f.write( "#" + modules.replace("\n", "\n#"))

def get_modules_versions():
    versions = dict()

    versions["python"] = platform.python_version()

    module_names = ["evoVGM", "numpy", "scipy", "pandas",
            "torch", "Bio", "joblib", "matplotlib", "pyvolve",
            "seaborn"]

    for module_name in module_names:
        found = importlib.util.find_spec(module_name)
        if found:
            module = importlib.import_module(module_name)
            versions[module_name] = module.__version__
        else:
            versions[module_name] = "Not found"

    return versions