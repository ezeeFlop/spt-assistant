#!/bin/bash

# Installation script for Voice Assistant Platform backend services

set -e # Exit immediately if a command exits with a non-zero status.

# --- Configuration ---
PROJECT_ROOT="$(pwd)"
PIPER_INSTALL_DIR="${PROJECT_ROOT}/piper_tts_install"
PIPER_APP_DIR="${PIPER_INSTALL_DIR}/piper_executable"
# PIPER_VOICES_DOWNLOAD_DIR deleted as voices are manual
PIPER_FINAL_VOICES_DIR="${PIPER_INSTALL_DIR}/voices" # Target for user-downloaded .onnx and .json files

# Piper TTS version (User specified working version)
PIPER_VERSION="2023.11.14-2"

REQUIRED_COMMANDS=("curl" "tar" "uv")

# --- Helper Functions ---

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

check_requirements() {
    echo "Checking for required commands..."
    for cmd in "${REQUIRED_COMMANDS[@]}"; do
        if ! command_exists "$cmd"; then
            echo "Error: Required command '$cmd' is not installed. Please install it and try again." >&2
            exit 1
        fi
    done
    echo "All required commands found."
}

install_piper_tts_executable() {
    echo ""
    echo "--- Setting up Piper TTS Executable --- (FR-07)"
    mkdir -p "${PIPER_APP_DIR}"
    # Voice directory will be created here too, for clarity, though voices are manual
    mkdir -p "${PIPER_FINAL_VOICES_DIR}"

    OS_TYPE="$(uname -s)"
    ARCH_TYPE="$(uname -m)"
    PIPER_EXECUTABLE_URL=""
    PIPER_EXECUTABLE_ARCHIVE=""

    echo "Detected OS: ${OS_TYPE}, Architecture: ${ARCH_TYPE}"

    # URLs are based on assets for release tag like "2023.11.14-2" (no "v" prefix for this tag)
    if [ "${OS_TYPE}" == "Linux" ]; then
        if [ "${ARCH_TYPE}" == "x86_64" ]; then
            PIPER_EXECUTABLE_URL="https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_x86_64.tar.gz"
            PIPER_EXECUTABLE_ARCHIVE="piper_linux_x86_64.tar.gz"
        elif [ "${ARCH_TYPE}" == "aarch64" ]; then
             PIPER_EXECUTABLE_URL="https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_aarch64.tar.gz"
             PIPER_EXECUTABLE_ARCHIVE="piper_linux_aarch64.tar.gz"
        # Add other Linux architectures if official binaries exist (e.g., armv7l)
        else
            echo "Warning: Unsupported Linux architecture '${ARCH_TYPE}' for automated Piper download." >&2
        fi
    elif [ "${OS_TYPE}" == "Darwin" ]; then # macOS
        if [ "${ARCH_TYPE}" == "arm64" ]; then # Apple Silicon (uname -m is arm64, GitHub asset uses aarch64 in name)
            PIPER_EXECUTABLE_URL="https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_macos_aarch64.tar.gz"
            PIPER_EXECUTABLE_ARCHIVE="piper_macos_aarch64.tar.gz" # Archive name as per user's successful download
        elif [ "${ARCH_TYPE}" == "x86_64" ]; then # Intel Macs
            PIPER_EXECUTABLE_URL="https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_macos_x86_64.tar.gz"
            PIPER_EXECUTABLE_ARCHIVE="piper_macos_x86_64.tar.gz"
        else
            echo "Warning: Unsupported macOS architecture '${ARCH_TYPE}' for automated Piper download." >&2
        fi
    else
        echo "Warning: Unsupported OS '${OS_TYPE}' for automated Piper download." >&2
    fi

    PIPER_EXECUTABLE_ACTUAL_PATH="${PIPER_APP_DIR}/piper/piper (CHECK MANUALLY)" # Default pessimistic path

    if [ -n "${PIPER_EXECUTABLE_URL}" ]; then
        echo "Downloading Piper TTS executable (${PIPER_VERSION} for ${OS_TYPE} ${ARCH_TYPE})..."
        echo "URL: ${PIPER_EXECUTABLE_URL}"
        DOWNLOAD_TARGET="${PIPER_INSTALL_DIR}/${PIPER_EXECUTABLE_ARCHIVE}"
        
        if curl --silent --show-error --location --fail --output "${DOWNLOAD_TARGET}" "${PIPER_EXECUTABLE_URL}"; then
            MIN_EXPECTED_SIZE=102400 # 100KB
            ACTUAL_SIZE=$(wc -c < "${DOWNLOAD_TARGET}")

            if [ "${ACTUAL_SIZE}" -lt "${MIN_EXPECTED_SIZE}" ]; then
                echo "Error: Downloaded file (${DOWNLOAD_TARGET}) is too small (${ACTUAL_SIZE} bytes)." >&2
                echo "This indicates the download did not retrieve the actual archive (expected at least ${MIN_EXPECTED_SIZE} bytes)." >&2
                echo "Please check your network connection and proxies, or try downloading the URL manually in a browser." >&2
                rm -f "${DOWNLOAD_TARGET}"
                PIPER_EXECUTABLE_URL="" 
            else
                echo "Downloaded ${PIPER_EXECUTABLE_ARCHIVE} (${ACTUAL_SIZE} bytes) successfully."
                echo "Extracting Piper executable..."
                if tar -xzf "${DOWNLOAD_TARGET}" -C "${PIPER_APP_DIR}"; then
                    # Standard structure is archive extracts to a 'piper' dir containing the executable
                    if [ -f "${PIPER_APP_DIR}/piper/piper" ]; then
                        PIPER_EXECUTABLE_ACTUAL_PATH="${PIPER_APP_DIR}/piper/piper"
                    # Some archives might extract directly or with a different top-level folder name
                    elif [ -f "${PIPER_APP_DIR}/piper" ]; then # Direct executable
                        PIPER_EXECUTABLE_ACTUAL_PATH="${PIPER_APP_DIR}/piper"
                    # Add other potential extracted paths if known
                    else
                        echo "Warning: Piper executable not found at common expected paths after extraction ('${PIPER_APP_DIR}/piper/piper' or '${PIPER_APP_DIR}/piper')." >&2
                        echo "Please inspect '${PIPER_APP_DIR}' to find the executable."
                    fi
                    echo "Piper executable assumed/found at or near: ${PIPER_EXECUTABLE_ACTUAL_PATH}"
                else
                    echo "Error: Failed to extract ${DOWNLOAD_TARGET}. The file might be corrupted or not a valid tar.gz archive." >&2
                    echo "Please try deleting it and running the script again, or download/extract manually." >&2
                    PIPER_EXECUTABLE_URL="" 
                fi
                rm -f "${DOWNLOAD_TARGET}"
            fi
        else
            echo "Error: curl command failed to download Piper executable from ${PIPER_EXECUTABLE_URL}. Exit code: $?" >&2
            echo "Please check your network connection, proxies, or if the URL is valid and accessible." >&2
            PIPER_EXECUTABLE_URL="" 
        fi
    fi

    if [ -z "${PIPER_EXECUTABLE_URL}" ]; then 
        echo "" 
        echo "--------------------------------------------------------------------------------" >&2
        echo "!! Automated Piper TTS executable setup FAILED or was not attempted for your system (${OS_TYPE} ${ARCH_TYPE})." >&2
        echo "!! Please download it manually for your OS/architecture from:" >&2
        echo "   https://github.com/rhasspy/piper/releases (Target version: ${PIPER_VERSION})" >&2
        echo "!! Extract the archive, and place the 'piper' executable into the directory:" >&2
        echo "   '${PIPER_APP_DIR}/piper/' (You may need to create the 'piper' subdirectory if the archive doesn't)." >&2
        echo "!! Then update PIPER_EXECUTABLE_PATH in tts_service/.env manually to this location." >&2
        echo "--------------------------------------------------------------------------------" >&2
    else
        echo "Piper TTS executable setup attempt complete. Check '${PIPER_APP_DIR}'."
    fi

    echo ""
    echo "--- Piper Voice Model Setup Instructions --- (Manual Download Required)"
    echo "The script will NOT automatically download voice model archives."
    echo "Please download the required French voice models manually:"
    echo "1. Go to the Piper voices repository on Hugging Face: https://huggingface.co/rhasspy/piper-voices/tree/main/fr/fr_FR"
    echo "2. Navigate into the subdirectories for the voices you need:"
    echo "   - For 'fr-FR-siwis-medium': navigate to 'siwis/medium/'"
    echo "   - For 'fr-FR-gilles-high': navigate to 'gilles/high/' (or similar, check quality availability)"
    echo "3. From each voice's specific directory on Hugging Face, download the .onnx file AND the .onnx.json file."
    echo "4. Place all downloaded .onnx and .onnx.json files DIRECTLY into the following directory:"
    echo "   ${PIPER_FINAL_VOICES_DIR}"
    echo "   (The script has created this directory: mkdir -p "${PIPER_FINAL_VOICES_DIR}")"
    echo "   For example, after download and placement, you should have files like:"
    echo "   - ${PIPER_FINAL_VOICES_DIR}/fr_FR-siwis-medium.onnx"
    echo "   - ${PIPER_FINAL_VOICES_DIR}/fr_FR-siwis-medium.onnx.json"
    echo "   (And similar for other voices like gilles-high if you download it)"
    echo ""
    echo "Ensure PIPER_VOICES_DIR in tts_service/.env points to: ${PIPER_FINAL_VOICES_DIR}"
}

install_piper_tts_executable # Renamed function

exit 0 