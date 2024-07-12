import os
import logging
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from dotenv import load_dotenv
import openai
import time

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Set up basic logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                     level=logging.INFO)
logger = logging.getLogger(__name__)

# OpenAI configuration
openai.api_key = OPENAI_API_KEY

def start(update, context):
    """Send a message when the command /start is issued."""
    update.message.reply_text('Hi! Send me an audio file or voice message for transcription.')


import openai
import time

def transcribe_audio(audio_file_path):
    """
    Transcribe the given audio file using OpenAI's Whisper API.

    :param audio_file_path: Path to the audio file to transcribe
    :return: Transcribed text
    """
    with open(audio_file_path, 'rb') as audio_file:
        # Transcribe the audio file
        response = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file,
            language='ru'  # Specify the language if needed
        )

    # Wait for the transcription to complete
    while not response['text']:
        time.sleep(5)  # Wait for 5 seconds before checking the status again
        response = openai.Audio.retrieve(response['id'])

    # Return the transcribed text
    return response['text']

def handle_audio(update, context):
    """Handle audio and voice messages."""
    file = update.message.voice.get_file() if update.message.voice else update.message.audio.get_file()
    file.download('audio_file.ogg')
    transcript = transcribe_audio('audio_file.ogg')
    
    if not transcript:
        update.message.reply_text('Sorry, I could not transcribe that audio.')
        return
    
    if len(transcript) > 4096:
        # Write the transcript to a text file
        text_file_path = 'transcript.txt'
        with open(text_file_path, 'w') as text_file:
            text_file.write(transcript)

        # Send the text file to the user
        with open(text_file_path, 'rb') as text_file:
            update.message.reply_document(text_file)
        return
    else:
        update.message.reply_text(transcript)
        return

def error(update, context):
    """Log Errors caused by Updates."""
    logger.warning(f'Update {update} caused error {context.error}')

def main():
    """Start the bot."""
    updater = Updater(TELEGRAM_TOKEN, use_context=True)

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.voice | Filters.audio, handle_audio))
    dp.add_error_handler(error)

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()