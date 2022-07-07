#!/usr/bin/env python

from evoVGM.simulations import evolve_seqs_full_homogeneity as evolve_sequences
from evoVGM.simulations import build_star_tree
from evoVGM.data import build_msa_categorical
from evoVGM.utils import timeSince
from evoVGM.utils import get_categorical_prior 
from evoVGM.utils import get_branch_prior 
from evoVGM.utils import get_kappa_prior 
from evoVGM.utils import str2floats, fasta_to_list
from evoVGM.utils import str_to_values
from evoVGM.utils import write_conf_packages
from evoVGM.reports import plt_elbo_ll_kl_rep_figure
from evoVGM.reports import aggregate_estimate_values
from evoVGM.reports import plot_fit_estim_dist
from evoVGM.reports import plot_fit_estim_corr

from evoVGM.models import compute_log_likelihood_data 
from evoVGM.models import EvoVGM_JC69
from evoVGM.models import EvoVGM_K80
from evoVGM.models import EvoVGM_GTR 

import sys
import os
from os import makedirs
import configparser
import time
from datetime import datetime

import numpy as np
import torch

from joblib import Parallel, delayed
from joblib import dump, load


__author__ = "amine remita"

"""
"""

## Evaluation function
## ###################
def eval_evomodel(EvoModel, m_args, in_args):
    # Instanciate the model
    e = EvoModel(**m_args)

    e.fit(in_args["X"],
            in_args["X_counts"],
            latent_sample_size=in_args["nb_samples"],
            sample_temp=in_args["sample_temp"], 
            alpha_kl=in_args["alpha_kl"], 
            max_iter=in_args["n_epochs"],
            optim=in_args["optim"], 
            optim_learning_rate=in_args["learning_rate"],
            optim_weight_decay=in_args["weight_decay"], 
            X_val=in_args["X_val"],
            X_val_counts=in_args["X_val_counts"],
            keep_val_history=True,
            verbose=False)

    fit_hist = [e.elbos_list, e.lls_list, e.kls_list]
    if in_args["X_val"] is not None:
        fit_hist.extend([
            e.elbos_val_list,
            e.lls_val_list,
            e.kls_val_list])

    fit_hist = np.array(fit_hist)
    val_hist_estim = e.val_estimates

    val_results = e.generate(
            in_args["X_val"],
            in_args["X_val_counts"],
            latent_sample_size=in_args["nb_samples"],
            sample_temp=in_args["sample_temp"], 
            alpha_kl=in_args["alpha_kl"])

    overall = dict(
        fit_hist=fit_hist,
        val_hist_estim=val_hist_estim,
        val_results=val_results)

    return overall


if __name__ == "__main__":

    if len(sys.argv) != 2:
        print("Config file is missing!!")
        sys.exit()

    print("RUN {}".format(sys.argv[0]), flush=True)

    ## Fetch argument values from ini file
    ## ###################################

    config_file = sys.argv[1]
    config = configparser.ConfigParser(
            interpolation=configparser.ExtendedInterpolation())

    with open(config_file, "r") as cf:
        config.read_file(cf)

    # IO files
    output_path = config.get("io", "output_path")
    scores_from_file = config.getboolean("io", "scores_from_file",
            fallback=False)

    # Sequence data
    from_fasta = config.getboolean("data", "from_fasta",
            fallback=False)
    nb_sites = config.getint("data", "alignment_size", fallback=100)
    sim_blengths = config.get("data", "branch_lengths",
            fallback="0.1,0.1")
    sim_rates = str_to_values(config.get("data", "rates",
        fallback="0.16"), 6, cast=float)
    sim_freqs = str_to_values(config.get("data", "freqs",
        fallback="0.25"), 4, cast=float)


    # setting parameters
    job_name = config.get("settings", "job_name", fallback=None)
    seed = config.getint("settings", "seed")
    device_str = config.get("settings", "device")
    verbose = config.get("settings", "verbose")

    # Evo variational model type
    evomodel_type = config.get("subvmodel", "evomodel")

    # Hyper parameters
    nb_replicates = config.getint("hperparams", "nb_replicates") 
    nb_samples = config.getint("hperparams", "nb_samples")
    h_dim = config.getint("hperparams", "hidden_size")
    nb_layers = config.getint("hperparams", "nb_layers", fallback=3)
    sample_temp = config.getfloat("hperparams", "sample_temp")
    alpha_kl = config.getfloat("hperparams", "alpha_kl")
    n_epochs = config.getint("hperparams", "n_epochs")
    learning_rate = config.getfloat("hperparams", "learning_rate")
    weight_decay = config.getfloat("hperparams",
            "optim_weight_decay")

    # Hyper-parameters of prior distributions
    ancestor_prior_conf = config.get("priors", "ancestor_prior", 
            fallback="uniform")
    branch_prior_conf = config.get("priors", "branch_prior", 
            fallback="0.1,0.1")
    kappa_prior_conf = config.get("priors", "kappa_prior", 
            fallback="1.,1.")
    rates_prior_conf = config.get("priors", "rates_prior",
            fallback="uniform")
    freqs_prior_conf = config.get("priors", "freqs_prior",
            fallback="uniform")

    # plotting settings
    size_font = config.getint("plotting", "size_font", fallback=16)
    plt_usetex = config.getboolean("plotting", "plt_usetex",
            fallback=False)
    print_xtick_every = config.getint("plotting",
            "print_xtick_every", fallback=10)

    # Process verbose
    if verbose.lower() == "false":
        verbose = 0
    elif verbose.lower() == "none":
        verbose = 0
    elif verbose.lower() == "true":
        verbose = 1
    else:
        try:
            verbose = int(verbose)
            if verbose < 0:
                print("\nInvalid value for verbose"\
                        " {}".format(verbose))
                print("Valid values are: True, False, None and"\
                        " positive integers")
                print("Verbose is set to 0")
                verbose = 0
        except ValueError as e:
            print("\nInvalid value for verbose {}".format(verbose))
            print("Valid values are: True, False, None and"\
                    " positive integers")
            print("Verbose is set to 1")
            verbose = 1

    if evomodel_type not in ["jc69", "k80", "gtr"]:
        print("evomodel_type should be jc69, k80 or gtr,"\
                " not {}".format(evomodel_type), file=sys.stderr)
        sys.exit()

    # Computing device setting
    if device_str != "cpu" and not torch.cuda.is_available():
        if verbose: 
            print("Cuda is not available. Changing device to 'cpu'")
        device_str = 'cpu'

    device = torch.device(device_str)

    if str(job_name).lower() in ["auto", "none"]:
        job_name = None

    if not job_name:
        now = datetime.now()
        job_name = now.strftime("%y%m%d%H%M")


    sim_params = dict(
            b=np.array(str2floats(sim_blengths)),
            r=np.array(sim_rates),
            f=np.array(sim_freqs),
            k=np.array([[sim_rates[0]/sim_rates[1]]])
            )

    ## output name file
    ## ################
    output_path = os.path.join(output_path, evomodel_type, job_name)
    makedirs(output_path, mode=0o700, exist_ok=True)

    ## Load results
    ## ############
    results_file = output_path+"/{}_results.pkl".format(job_name)
    # training sequences
    x_fasta_file = output_path+"/{}_train.fasta".format(job_name)
    # validation sequences
    v_fasta_file = output_path+"/{}_valid.fasta".format(job_name)

    if os.path.isfile(results_file) and scores_from_file:
        if verbose: print("\nLoading scores from file")
        result_data = load(results_file)
        rep_results=result_data["rep_results"]
        logl_data=result_data["logl_data"]

        # Get validation sequences
        av_sequences = fasta_to_list(v_fasta_file, verbose)
        av_motifs_cats = build_msa_categorical(av_sequences)
        AV = av_motifs_cats.data

    ## Execute the evaluation
    ## ######################
    else:
        if verbose: print("\nRunning the evaluation..")

        ## Data preparation
        ## ################
        # Evolve sequences

        if os.path.isfile(x_fasta_file) and\
                os.path.isfile(v_fasta_file) and from_fasta:
            ax_sequences = fasta_to_list(x_fasta_file, verbose)
            av_sequences = fasta_to_list(v_fasta_file, verbose)

            x_root = ax_sequences[0]
            x_sequences = ax_sequences[1:]

            v_root = av_sequences[0]
            v_sequences = av_sequences[1:]

        else: 
            tree=build_star_tree(sim_blengths)

            x_root, x_sequences = evolve_sequences(
                    tree,
                    fasta_file=x_fasta_file,
                    nb_sites=nb_sites,
                    subst_rates=sim_rates,
                    state_freqs=sim_freqs,
                    return_anc=True,
                    seed=seed,
                    verbose=verbose)

            v_root, v_sequences = evolve_sequences(
                    tree,
                    fasta_file=v_fasta_file,
                    nb_sites=nb_sites,
                    subst_rates=sim_rates,
                    state_freqs=sim_freqs,
                    return_anc=True,
                    seed=seed+42,
                    verbose=verbose)

        # Transform training sequences
        x_motifs_cats = build_msa_categorical(x_sequences)
        X = torch.from_numpy(x_motifs_cats.data).to(device)
        X, X_counts = X.unique(dim=0, return_counts=True)

        # Transform validation sequences
        # No need to get unique sites.
        # Validation need only forward pass and it's fast.
        v_motifs_cats = build_msa_categorical(v_sequences)
        V = torch.from_numpy(v_motifs_cats.data).to(device)
        V_counts = None 
 
        # Transform Val sequences including ancestral sequence
        # This will be used to compute the true logl knowing
        # the true parameters
        all_val_seqs = [v_root, *v_sequences]
        av_motifs_cats = build_msa_categorical(all_val_seqs)
        AV = av_motifs_cats.data
        AV_unique, AV_counts = torch.from_numpy(AV).unique(
                dim=0, return_counts=True)

        logl_data = compute_log_likelihood_data(AV_unique, AV_counts,
                sim_blengths, sim_rates, sim_freqs)

        if verbose:
            print("\nLog likelihood of the data {}\n".format(
                logl_data))

        x_dim = 4
        a_dim = 4
        m_dim = len(x_sequences) # Number of sequences

        ## Get prior values
        ## ################

        ancestor_prior = get_categorical_prior(ancestor_prior_conf,
                "ancestor", verbose=verbose)
        branch_prior = get_branch_prior(branch_prior_conf,
                verbose=verbose)

        if evomodel_type == "gtr":
            # Get rate and freq priors if the model is EvoGTRNVMSA_KL
            rates_prior = get_categorical_prior(rates_prior_conf, 
                    "rates", verbose=verbose)
            freqs_prior = get_categorical_prior(freqs_prior_conf,
                    "freqs", verbose=verbose)
        
        elif evomodel_type == "k80":
            kappa_prior = get_kappa_prior(kappa_prior_conf, 
                    verbose=verbose)

        ## Evo model type
        ## ##############

        if evomodel_type == "gtr":
            EvoModelClass = EvoVGM_GTR
        elif evomodel_type == "k80":
            EvoModelClass = EvoVGM_K80
        else:
            EvoModelClass = EvoVGM_JC69

        model_args = {
                "x_dim":x_dim,
                "a_dim":a_dim,
                "h_dim":h_dim,
                "m_dim":m_dim,
                "ancestor_prior":ancestor_prior,
                "branch_prior":branch_prior,
                "device":device
                }

        if evomodel_type == "gtr":
            # Add rate and freq priors if the model is EvoGTRNVMSA_KL
            model_args["rates_prior"] = rates_prior
            model_args["freqs_prior"] = freqs_prior

        elif evomodel_type == "k80":
            model_args["kappa_prior"] = kappa_prior

        input_args = {
                "X":X,
                "X_counts":X_counts,
                "X_val":V,
                "X_val_counts":V_counts,
                "nb_samples":nb_samples,
                "sample_temp":sample_temp,
                "alpha_kl":alpha_kl,
                "n_epochs":n_epochs,
                "optim":"adam",
                "learning_rate":learning_rate,
                "weight_decay":weight_decay
                }

        parallel = Parallel(n_jobs=nb_replicates, 
                prefer="processes", verbose=verbose)

        rep_results = parallel(delayed(eval_evomodel)(EvoModelClass,
            model_args, input_args) for s in range(nb_replicates))

        #
        result_data = dict(
                rep_results=rep_results,
                logl_data=logl_data
                )
        dump(result_data, results_file)

    scores = [result["fit_hist"] for result in rep_results]

    # get min number of epoch of all reps 
    # (maybe some reps stopped before max_iter)
    # to slice the list of epochs with the same length 
    # and be able to cast the list in ndarray        
    min_iter = scores[0].shape[1]
    for score in scores:
        if min_iter >= score.shape[1]: min_iter = score.shape[1]
    the_scores = []
    for score in scores:
        the_scores.append(score[:,:min_iter])

    the_scores = np.array(the_scores)
    #print(the_scores)

    ## Ploting results
    ## ###############
    title = output_path

    if verbose: print("\nPlotting..")

    plt_elbo_ll_kl_rep_figure(
            the_scores,
            output_path+"/{}_rep_fig".format(job_name),
            sizefont=size_font,
            usetex=plt_usetex,
            print_xtick_every=print_xtick_every,
            title=title,
            plot_validation=True)

    estimates = aggregate_estimate_values(rep_results,
            "val_hist_estim")
    #return a dictionary of arrays

    plot_fit_estim_dist(
            estimates, 
            sim_params,
            output_path+"/{}_val_estim_dist".format(job_name),
            sizefont=size_font,
            usetex=plt_usetex,
            print_xtick_every=print_xtick_every,
            y_limits=[-0.1, 1.1],
            legend='upper right')

    plot_fit_estim_corr(
            estimates, 
            sim_params,
            output_path+"/{}_val_estim_corr".format(job_name),
            sizefont=size_font,
            usetex=plt_usetex,
            print_xtick_every=print_xtick_every,
            y_limits=[-1.1, 1.1],
            legend='lower right')

    conf_file = output_path+"/{}_conf.ini".format(job_name)
    if not os.path.isfile(conf_file):
        write_conf_packages(config, conf_file)

    print("\nFin normale du programme\n")
