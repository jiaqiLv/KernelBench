import subprocess
import os, sys
from .utils import (
    query_server,
    read_file,
    extract_first_code,
)
from .dataset import (
    construct_problem_dataset_from_problem_dir
)
from .prompt_constructor import (
    prompt_generate_custom_cuda_from_file_one_example,
    prompt_generate_custom_cuda_oneshot_and_template,
    prompt_fix_compile,
    prompt_fix_correctness,
)
from .eval import (
    eval_kernel_against_ref,
    KernelExecResult,
    fetch_ref_arch_from_problem_id,
    fetch_ref_arch_from_level_problem_id,
)

from .dataset import get_kernelbench_subset

REPO_TOP_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
    )
)
KERNEL_BENCH_PATH = os.path.join(REPO_TOP_PATH, "KernelBench")
import subprocess
import os, sys
from .utils import (
    query_server,
    read_file,
    extract_first_code,
)
from .dataset import (
    construct_problem_dataset_from_problem_dir
)
from .prompt_constructor import (
    prompt_generate_custom_cuda_from_file_one_example,
    prompt_generate_custom_cuda_oneshot_and_template,
    prompt_fix_compile,
    prompt_fix_correctness,
)
from .eval import (
    eval_kernel_against_ref,
    KernelExecResult,
    fetch_ref_arch_from_problem_id,
    fetch_ref_arch_from_level_problem_id,
)

from .dataset import get_kernelbench_subset

REPO_TOP_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
    )
)
KERNEL_BENCH_PATH = os.path.join(REPO_TOP_PATH, "KernelBench")

SERVER_TYPE = "gemini"

server_args = {
    "deepseek": {"temperature": 1.6, "max_tokens": 4096},
    "gemini": {},  # need to experiment with temperature,
    "together": {  # this is Llama 3.1
        "model_name": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "temperature": 0.7,
        "max_tokens": 4096,
    },
    "sglang": {  # this is Llama 3
        "temperature": 0.7,
    },
}


def run_llm(prompt, server_type=SERVER_TYPE, temperature=None):
    """
    query the LLM server with the prompt
    """
    if temperature is not None: # always override temperature
        server_args[server_type]["temperature"] = temperature
    return query_server(prompt, server_type=server_type, **server_args[server_type])


def get_temperature_sweep_generations(
    server_type, temperatures, level_num, problem_id, num_samples=30
):
    ref_arch_name, ref_arch_src = fetch_ref_arch_from_level_problem_id(
        level_num, problem_id, with_name=True
    )
    os.makedirs(os.path.join(REPO_TOP_PATH, f"results/"), exist_ok=True)
    os.makedirs(
        os.path.join(REPO_TOP_PATH, f"results/temperature_sweep/"), exist_ok=True
    )
    for temperature in temperatures:
        for sample_ind in range(num_samples):
            # save generation in results/temperature_sweep/server_type/level_num/problem_id/temp{temperature}_sample_{sample_ind}.txt
            file_path = os.path.join(
                REPO_TOP_PATH,
                f"results/temperature_sweep/{server_type}_level{level_num}_problem{problem_id}_temp{temperature}_sample_{sample_ind}.txt",
            )
            if os.path.exists(file_path):
                print(f"Skipping {file_path} because it already exists")
                continue
            prompt = prompt_generate_custom_cuda_from_file_one_example(
                ref_arch_src, example_ind=1
            )
            result = run_llm(prompt, server_type, temperature)
            with open(file_path, "w") as f:
                f.write(result)


def get_custom_cuda(prompt):
    custom_cuda = run_llm(prompt)
    custom_cuda = extract_first_code(custom_cuda, "python")
    return custom_cuda


def run(
    ref_arch_src, 
    save_prompt=False, 
    use_combined_prompt=False, 
    prompt_example_ind=1,
    inference_fn=run_llm
) -> KernelExecResult:
    os.makedirs(os.path.join(REPO_TOP_PATH, "src/scratch"), exist_ok=True)

    # generate custom CUDA, save in scratch/model_new.py
    if use_combined_prompt:
        fn_get_prompt = prompt_generate_custom_cuda_oneshot_and_template
        custom_cuda_prompt = fn_get_prompt(ref_arch_src)
    else:
        fn_get_prompt = prompt_generate_custom_cuda_from_file_one_example
        custom_cuda_prompt = fn_get_prompt(ref_arch_src, prompt_example_ind)
    if save_prompt:
        with open(os.path.join(REPO_TOP_PATH, "src/scratch/prompt.txt"), "w") as f:
            f.write(custom_cuda_prompt)

    # custom_cuda = get_custom_cuda(custom_cuda_prompt)
    custom_cuda = inference_fn(custom_cuda_prompt)
    custom_cuda = extract_first_code(custom_cuda, "python")

    # check LLM is able to generate custom CUDA code
    assert custom_cuda is not None, "Custom CUDA code generation failed"
    
    # this should be optional
    # with open(os.path.join(REPO_TOP_PATH, "src/scratch/model_new.py"), "w") as f:
    #     f.write(custom_cuda)

    kernel_exec_result = eval_kernel_against_ref(
        ref_arch_src, custom_cuda, verbose=False, measure_performance=False
    )
    return (custom_cuda, kernel_exec_result)


# IDK WHAT THIS PART IS FOR


def compare_results(best_result, new_result):
    if best_result is None:
        return True
    if new_result.compiled and not best_result.compiled:
        return True
    if new_result.correctness and not best_result.correctness:
        return True
    # TODO: compare performance


def run_multiturn(ref_arch_src, turns=10) -> KernelExecResult:
    # NOTE: WIP

    custom_cuda, result = run(ref_arch_src)
    best_custom_cuda = custom_cuda
    best_result = result

    for turn in range(turns):
        if not result.compiled:
            print(f"Turn {turn}: Fixing compilation error")
            print(f"Metadata: {result.metadata}")
            custom_cuda = get_custom_cuda(
                prompt_fix_compile(ref_arch_src, custom_cuda, result.metadata)
            )
            result = eval_kernel_against_ref(
                ref_arch_src, custom_cuda, verbose=False, measure_performance=False
            )
        elif not result.correctness:
            print(f"Turn {turn}: Fixing correctness error")
            print(f"Metadata: {result.metadata}")
            custom_cuda = get_custom_cuda(
                prompt_fix_correctness(ref_arch_src, custom_cuda, result.metadata)
            )
            result = eval_kernel_against_ref(
                ref_arch_src, custom_cuda, verbose=False, measure_performance=False
            )
        else:
            # TODO: we should try to improve performance
            # custom_cuda = get_custom_cuda(improve_perf_prompt)
            # result = eval_kernel_against_ref(ref_arch_src, custom_cuda, verbose=False, measure_performance=False)
            print(f"Turn {turn}: Improving performance")
        if compare_results(best_result, result):
            best_result = result
            best_custom_cuda = custom_cuda

    return (best_custom_cuda, best_result)


if __name__ == "__main__":

    # PROBLEM_DIR = os.path.join(KERNEL_BENCH_PATH, "level2")
    # dataset = construct_problem_dataset_from_problem_dir(PROBLEM_DIR)
    # ref_arch_src = fetch_ref_arch_from_problem_id(17, dataset)
    # # write to scratch/model.py
    # with open(os.path.join(REPO_TOP_PATH, "src/scratch/model.py"), "w") as f:
    #     f.write(ref_arch_src)

    # run with one-shot + template combined prompt
    # print(run(ref_arch_src, use_combined_prompt=True))

    # # run with one-shot from file prompt
    # print(run(ref_arch_src, use_combined_prompt=False, prompt_example_ind=1))

    # # run with template prompt
    # print(run(ref_arch_src, use_combined_prompt=False, prompt_example_ind=2))

    # run multiturn with combined prompt
    # print(run_multiturn(ref_arch_src))

    # run temperature sweep
    # get kernelbench subset
    kernelbench_subset = (
        get_kernelbench_subset(level=1, num_problems=5)
        + get_kernelbench_subset(level=2, num_problems=3)
        + get_kernelbench_subset(level=3, num_problems=2)
    )
    for level, problem_id in kernelbench_subset:
        get_temperature_sweep_generations(
            server_type="gemini",
            temperatures=[0.7, 1.0, 1.3, 1.6],
            level_num=level,
            problem_id=problem_id,
        )
        # TODO: deepseek, gemini, gpt, claude, llama