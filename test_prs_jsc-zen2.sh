python3 ./boegelbot.py --mode test_pr --github-user boegelbot --owner SebastianAchilles --host jsc-zen2 --gpuhost jsc-zen2-v100 --core-cnt 8 --gpu-job-opt "--gres=gpu:1" --pr-test-cmd "EB_PR=%(pr)s EB_ARGS=%(eb_args)s /opt/software/slurm/bin/sbatch --job-name test_PR_%(pr)s --ntasks=%(core_cnt)s %(slurm_args)s ~/boegelbot/eb_from_pr_upload_jsc-zen2.sh"
