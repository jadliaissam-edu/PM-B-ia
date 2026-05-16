import os
# ─── Résolution du conflit OpenMP (Anaconda Windows) ──────────────────────────
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import shutil
import tempfile
import torch

# ─── Configuration automatique de FFmpeg ─────────────────────────────────────
# Pour éviter l'erreur "FileNotFoundError: [WinError 2] The system cannot find the file specified"
# car Whisper requiert FFmpeg dans le PATH système.
try:
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    ffmpeg_dir = os.path.dirname(ffmpeg_exe)
    
    # Whisper appelle "ffmpeg", on s'assure qu'un exécutable nommé "ffmpeg.exe" (ou "ffmpeg") existe.
    target_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    target_path = os.path.join(ffmpeg_dir, target_name)
    
    if not os.path.exists(target_path):
        print(f"--- Configuration FFmpeg : Copie de {ffmpeg_exe} vers {target_path} ---")
        shutil.copy2(ffmpeg_exe, target_path)
    
    # Ajout du répertoire au PATH pour que Whisper puisse le localiser
    if ffmpeg_dir not in os.environ["PATH"]:
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ["PATH"]
        print(f"--- Configuration FFmpeg : Ajouté au PATH ({ffmpeg_dir}) ---")
except Exception as ffmpeg_err:
    print(f"--- ATTENTION : Échec de la configuration FFmpeg via imageio_ffmpeg : {ffmpeg_err} ---")

# Import de whisper après avoir configuré le PATH
import whisper

# ─── Initialisation du modèle Whisper Local ──────────────────────────────────
# Détection automatique du GPU (CUDA) pour plus de performance
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

print(f"--- Initialisation de Whisper Local ({DEVICE}) ---")
# On utilise le modèle 'base' (74M params) : bon compromis vitesse/précision
model_whisper = whisper.load_model("base", device=DEVICE)
print("--- Modèle Whisper chargé et prêt ! ---")


async def transcribe_audio(file_content: bytes, filename: str, language: str = "fr") -> str:
    """
    Transcrit un fichier audio via le modèle OpenAI Whisper installé localement.
    """
    # Création d'un fichier temporaire pour que Whisper puisse le lire
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_audio:
        temp_audio.write(file_content)
        temp_path = temp_audio.name

    try:
        # Transcription locale officielle (sans internet)
        resultat = model_whisper.transcribe(
            temp_path, 
            language=language, 
            task="transcribe"
        )
        
        texte_transcrit = resultat.get("text", "")
        print(f"DEBUG Whisper Local : {texte_transcrit}")
        
        return texte_transcrit.strip()

    except Exception as e:
        print(f"EXCEPTION Whisper Local : {str(e)}")
        raise Exception(f"Erreur lors de la transcription locale : {str(e)}")
    
    finally:
        # Nettoyage du fichier temporaire
        if os.path.exists(temp_path):
            os.remove(temp_path)


# ─── Fonction Standalone (Microphone) ────────────────────────────────────────
def transcrire_vocal_local():
    """
    Capture l'audio du microphone et transcrit via Whisper.
    Nécessite SpeechRecognition et PyAudio.
    """
    try:
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        
        with sr.Microphone() as source:
            print("Écoute (Microphone Local)... Parlez maintenant.")
            recognizer.adjust_for_ambient_noise(source, duration=0.8)
            audio = recognizer.listen(source)
            
            # Transcription en utilisant les bytes capturés
            wav_data = audio.get_wav_data()
            return model_whisper.transcribe(wav_data)["text"].strip()
    except Exception as e:
        print(f"Erreur Microphone : {e}")
        return ""

if __name__ == "__main__":
    # Test rapide en local
    print("Test transcription locale...")
