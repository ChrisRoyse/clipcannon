#!/bin/bash
# RAD-NeRF Training Pipeline for ClipCannon
# Usage: ./scripts/train_radnerf.sh <name> [stage]
# Example: ./scripts/train_radnerf.sh nate       # runs all 3 stages
# Example: ./scripts/train_radnerf.sh nate head   # runs head only
# Example: ./scripts/train_radnerf.sh nate lips   # runs lip finetune only
# Example: ./scripts/train_radnerf.sh nate torso  # runs torso only

set -e

NAME="${1:?Usage: $0 <name> [head|lips|torso]}"
STAGE="${2:-all}"
RADNERF_DIR="$HOME/.clipcannon/models/rad-nerf"
DATA_DIR="$RADNERF_DIR/data/$NAME"
TRIAL_DIR="$RADNERF_DIR/trial_${NAME}"
TORSO_DIR="$RADNERF_DIR/trial_${NAME}_torso"

if [ ! -d "$DATA_DIR" ]; then
    echo "Error: Training data not found at $DATA_DIR"
    echo "Run preprocessing first: cd $RADNERF_DIR && python data_utils/process.py data/$NAME/$NAME.mp4"
    exit 1
fi

if ! docker images | grep -q radnerf-train; then
    echo "Error: Docker image 'radnerf-train' not found"
    echo "Build it: cd $RADNERF_DIR && docker build -f Dockerfile.train -t radnerf-train ."
    exit 1
fi

DOCKER_CMD="docker run --gpus all --rm \
    -v $DATA_DIR:/workspace/data/$NAME \
    -v $TRIAL_DIR:/workspace/trial_${NAME} \
    -v $TORSO_DIR:/workspace/trial_${NAME}_torso \
    -e TORCH_CUDA_ARCH_LIST=8.0 \
    radnerf-train"

mkdir -p "$TRIAL_DIR" "$TORSO_DIR"

# Stage 1: Head model (200K iterations, ~2-3 hours on RTX 5090)
if [ "$STAGE" = "all" ] || [ "$STAGE" = "head" ]; then
    echo "=========================================="
    echo "Stage 1: Head model training (200K iters)"
    echo "=========================================="
    $DOCKER_CMD main.py data/$NAME/ --workspace trial_${NAME}/ -O --iters 200000
    echo "Head training complete!"
fi

# Stage 2: Lip finetune (+50K iterations, ~45 min)
if [ "$STAGE" = "all" ] || [ "$STAGE" = "lips" ]; then
    echo "=========================================="
    echo "Stage 2: Lip finetuning (+50K iters)"
    echo "=========================================="
    $DOCKER_CMD main.py data/$NAME/ --workspace trial_${NAME}/ -O --iters 250000 --finetune_lips
    echo "Lip finetune complete!"
fi

# Stage 3: Torso model (200K iterations, ~2-3 hours)
if [ "$STAGE" = "all" ] || [ "$STAGE" = "torso" ]; then
    echo "=========================================="
    echo "Stage 3: Torso model training (200K iters)"
    echo "=========================================="
    # Find the latest head checkpoint
    HEAD_CKPT=$(ls -t "$TRIAL_DIR/checkpoints/"*.pth 2>/dev/null | head -1)
    if [ -z "$HEAD_CKPT" ]; then
        echo "Error: No head checkpoint found in $TRIAL_DIR/checkpoints/"
        exit 1
    fi
    CKPT_NAME=$(basename "$HEAD_CKPT")
    $DOCKER_CMD main.py data/$NAME/ --workspace trial_${NAME}_torso/ -O --torso \
        --head_ckpt trial_${NAME}/checkpoints/$CKPT_NAME --iters 200000
    echo "Torso training complete!"
fi

echo ""
echo "=========================================="
echo "Training complete for: $NAME"
echo "Head model: $TRIAL_DIR/checkpoints/"
echo "Torso model: $TORSO_DIR/checkpoints/"
echo ""
echo "Test with:"
echo "  docker run --gpus all -v $DATA_DIR:/workspace/data/$NAME \\"
echo "    -v $TRIAL_DIR:/workspace/trial_${NAME} \\"
echo "    -v $TORSO_DIR:/workspace/trial_${NAME}_torso \\"
echo "    radnerf-train main.py data/$NAME/ --workspace trial_${NAME}_torso/ -O --torso --test"
echo "=========================================="
