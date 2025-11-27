"""
Voice handler module for speech-to-speech interaction using OpenAI's GPT-4o Realtime API.
This module handles:
- Voice channel connection management
- Audio streaming to/from OpenAI Realtime API via WebSocket
- Audio playback using FFmpeg
- Voice input capture using discord-ext-voice-recv

Debug Logging:
- Set logging level to DEBUG to see detailed timing information
- Useful for diagnosing slow response times in voice sessions
"""

import asyncio
import base64
import json
import logging
import struct
import io
import time
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List, Tuple
from collections import deque

import discord
from discord import VoiceClient
import websockets
from websockets.protocol import State as WebSocketState

# Import voice receive extension
try:
    from discord.ext import voice_recv
    VOICE_RECV_AVAILABLE = True
except ImportError:
    VOICE_RECV_AVAILABLE = False

import config
from model_interface import get_model_generator

logger = logging.getLogger(__name__)

# Debug logging constants (defined early so classes can reference them)
DEBUG_LOG_AUDIO_CHUNK_INTERVAL = 50  # Log audio stats every N chunks (avoids log spam)
DEBUG_LOG_PROMPT_TRUNCATE_LENGTH = 50  # Maximum characters to show in prompt logs
DEBUG_HEARTBEAT_INTERVAL_LOOPS = 3000  # Heartbeat log every N loops (3000 * 0.1s = 5 minutes)


class VoiceDebugTimer:
    """
    Utility class for tracking timing of voice pipeline operations.
    Provides detailed timing information when DEBUG logging is enabled.
    """
    
    def __init__(self, operation_name: str):
        self.operation_name = operation_name
        self.start_time = None
        self.checkpoints: List[Tuple[str, float]] = []
    
    def start(self):
        """Start timing an operation."""
        self.start_time = time.perf_counter()
        self.checkpoints = []
        logger.debug(f"[TIMING] {self.operation_name} - STARTED at {datetime.now().isoformat()}")
    
    def checkpoint(self, name: str):
        """Record a checkpoint with elapsed time."""
        if self.start_time is None:
            return
        elapsed = (time.perf_counter() - self.start_time) * 1000  # Convert to ms
        self.checkpoints.append((name, elapsed))
        logger.debug(f"[TIMING] {self.operation_name} - {name}: {elapsed:.2f}ms elapsed")
    
    def end(self):
        """End timing and log total duration."""
        if self.start_time is None:
            return
        total = (time.perf_counter() - self.start_time) * 1000
        logger.debug(f"[TIMING] {self.operation_name} - COMPLETED in {total:.2f}ms at {datetime.now().isoformat()}")
        return total


class VoiceSessionStats:
    """
    Tracks statistics for a voice session for debugging purposes.
    """
    
    def __init__(self):
        self.session_start_time: Optional[float] = None
        self.audio_chunks_sent: int = 0
        self.audio_chunks_received: int = 0
        self.audio_bytes_sent: int = 0
        self.audio_bytes_received: int = 0
        self.speech_events: int = 0
        self.response_events: int = 0
        self.function_calls: int = 0
        self.last_audio_sent_time: Optional[float] = None
        self.last_audio_received_time: Optional[float] = None
        self.last_speech_start_time: Optional[float] = None
        self.last_response_start_time: Optional[float] = None
    
    def start_session(self):
        """Mark session start time."""
        self.session_start_time = time.perf_counter()
        logger.debug(f"[STATS] Voice session started at {datetime.now().isoformat()}")
    
    def record_audio_sent(self, byte_count: int):
        """Record audio chunk sent to OpenAI."""
        self.audio_chunks_sent += 1
        self.audio_bytes_sent += byte_count
        self.last_audio_sent_time = time.perf_counter()
        if self.audio_chunks_sent % DEBUG_LOG_AUDIO_CHUNK_INTERVAL == 0:
            logger.debug(f"[STATS] Audio sent: {self.audio_chunks_sent} chunks, {self.audio_bytes_sent} bytes total")
    
    def record_audio_received(self, byte_count: int):
        """Record audio chunk received from OpenAI."""
        self.audio_chunks_received += 1
        self.audio_bytes_received += byte_count
        self.last_audio_received_time = time.perf_counter()
        if self.audio_chunks_received % DEBUG_LOG_AUDIO_CHUNK_INTERVAL == 0:
            logger.debug(f"[STATS] Audio received: {self.audio_chunks_received} chunks, {self.audio_bytes_received} bytes total")
    
    def record_speech_start(self):
        """Record when user speech is detected."""
        self.speech_events += 1
        self.last_speech_start_time = time.perf_counter()
        logger.debug(f"[STATS] Speech event #{self.speech_events} started at {datetime.now().isoformat()}")
    
    def record_response_start(self):
        """Record when bot starts generating response."""
        self.response_events += 1
        self.last_response_start_time = time.perf_counter()
        if self.last_speech_start_time:
            latency = (self.last_response_start_time - self.last_speech_start_time) * 1000
            logger.debug(f"[STATS] Response #{self.response_events} started - latency from speech start: {latency:.2f}ms")
        else:
            logger.debug(f"[STATS] Response #{self.response_events} started at {datetime.now().isoformat()}")
    
    def record_function_call(self, function_name: str):
        """Record a function call."""
        self.function_calls += 1
        logger.debug(f"[STATS] Function call #{self.function_calls}: {function_name}")
    
    def get_summary(self) -> str:
        """Get a summary of session statistics."""
        if self.session_start_time:
            duration = time.perf_counter() - self.session_start_time
        else:
            duration = 0
        
        return (
            f"Session Duration: {duration:.1f}s | "
            f"Audio Sent: {self.audio_chunks_sent} chunks ({self.audio_bytes_sent} bytes) | "
            f"Audio Received: {self.audio_chunks_received} chunks ({self.audio_bytes_received} bytes) | "
            f"Speech Events: {self.speech_events} | "
            f"Responses: {self.response_events} | "
            f"Function Calls: {self.function_calls}"
        )


# Default model for voice image generation
DEFAULT_VOICE_IMAGE_MODEL = "nanobanana"

# OpenAI Realtime API WebSocket URL
OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"

# Audio format constants for Discord (48kHz, 16-bit PCM, stereo)
DISCORD_SAMPLE_RATE = 48000
DISCORD_CHANNELS = 2
DISCORD_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes

# Audio format constants for OpenAI Realtime API (24kHz, 16-bit PCM, mono)
OPENAI_SAMPLE_RATE = 24000
OPENAI_CHANNELS = 1
OPENAI_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes

# Buffer sizes
AUDIO_BUFFER_SIZE = 4800  # 200ms of audio at 24kHz


class AudioResampler:
    """Simple audio resampler for converting between sample rates."""
    
    @staticmethod
    def resample_48k_stereo_to_24k_mono(audio_data: bytes) -> bytes:
        """
        Convert Discord audio (48kHz stereo) to OpenAI format (24kHz mono).
        
        Args:
            audio_data: Raw PCM audio bytes (48kHz, 16-bit, stereo)
            
        Returns:
            Resampled PCM audio bytes (24kHz, 16-bit, mono)
        """
        if not audio_data:
            return b''
        
        # Unpack as 16-bit signed integers
        num_samples = len(audio_data) // 2
        samples = struct.unpack(f'<{num_samples}h', audio_data)
        
        # Convert stereo to mono by averaging channels
        mono_samples = []
        for i in range(0, len(samples), 2):
            if i + 1 < len(samples):
                avg = (samples[i] + samples[i + 1]) // 2
                mono_samples.append(avg)
        
        # Downsample from 48kHz to 24kHz (take every other sample)
        downsampled = mono_samples[::2]
        
        # Pack back to bytes
        return struct.pack(f'<{len(downsampled)}h', *downsampled)
    
    @staticmethod
    def resample_24k_mono_to_48k_stereo(audio_data: bytes) -> bytes:
        """
        Convert OpenAI audio (24kHz mono) to Discord format (48kHz stereo).
        
        Args:
            audio_data: Raw PCM audio bytes (24kHz, 16-bit, mono)
            
        Returns:
            Resampled PCM audio bytes (48kHz, 16-bit, stereo)
        """
        if not audio_data:
            return b''
        
        # Unpack as 16-bit signed integers
        num_samples = len(audio_data) // 2
        samples = struct.unpack(f'<{num_samples}h', audio_data)
        
        # Upsample from 24kHz to 48kHz: duplicate each sample (2x)
        # Convert mono to stereo: duplicate each upsampled sample for L and R channels (2x)
        # Total: each original sample becomes 4 samples (sample, sample, sample, sample)
        # This gives us: 24kHz mono -> 48kHz stereo
        stereo_upsampled = []
        for sample in samples:
            # 4 values per sample: 2 for upsampling * 2 for stereo channels
            stereo_upsampled.extend([sample, sample, sample, sample])
        
        # Pack back to bytes
        return struct.pack(f'<{len(stereo_upsampled)}h', *stereo_upsampled)


class OpenAIRealtimeSession:
    """Manages a WebSocket connection to OpenAI's Realtime API."""
    
    def __init__(self, on_audio_response: Callable[[bytes], None], on_text_response: Optional[Callable[[str], None]] = None, on_image_generated: Optional[Callable[[Any, str], None]] = None):
        """
        Initialize the OpenAI Realtime session.
        
        Args:
            on_audio_response: Callback function to handle audio response data
            on_text_response: Optional callback for text transcription responses
            on_image_generated: Optional callback when an image is generated (image, prompt)
        """
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.on_audio_response = on_audio_response
        self.on_text_response = on_text_response
        self.on_image_generated = on_image_generated
        self._running = False
        self._receive_task: Optional[asyncio.Task] = None
        self._audio_buffer = bytearray()
        self._response_in_progress = False
        self._pending_function_calls: Dict[str, Dict[str, Any]] = {}  # Track pending function calls
        self._stats = VoiceSessionStats()  # Debug statistics tracking
        
    async def connect(self) -> tuple[bool, Optional[str]]:
        """
        Establish WebSocket connection to OpenAI Realtime API.
        
        Returns:
            Tuple of (True, None) if connection successful, or (False, error_reason) on failure
        """
        timer = VoiceDebugTimer("OpenAI WebSocket Connect")
        timer.start()
        
        if not config.OPENAI_API_KEY:
            error_msg = "OPENAI_API_KEY not configured"
            logger.error(error_msg)
            return False, error_msg
        
        try:
            # Build URL with model parameter
            url = f"{OPENAI_REALTIME_URL}?model={config.OPENAI_REALTIME_MODEL}"
            logger.debug(f"[DEBUG] Connecting to OpenAI Realtime API: {url}")
            
            # Connect with API key in header
            headers = {
                "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1"
            }
            
            self.websocket = await websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=30
            )
            timer.checkpoint("WebSocket connected")
            
            self._running = True
            self._stats.start_session()
            
            # Configure the session
            await self._configure_session()
            timer.checkpoint("Session configured")
            
            # Start receiving messages
            self._receive_task = asyncio.create_task(self._receive_loop())
            
            timer.end()
            logger.info("Connected to OpenAI Realtime API")
            return True, None
            
        except websockets.exceptions.InvalidStatusCode as e:
            error_msg = f"OpenAI API returned invalid status code {e.status_code}"
            logger.error(error_msg)
            timer.end()
            return False, error_msg
        except websockets.exceptions.WebSocketException as e:
            error_msg = f"WebSocket connection error: {type(e).__name__}: {e}"
            logger.error(error_msg)
            timer.end()
            return False, error_msg
        except Exception as e:
            error_msg = f"OpenAI connection error: {type(e).__name__}: {e}"
            logger.error(error_msg)
            timer.end()
            return False, error_msg
    
    async def _configure_session(self):
        """Send session configuration to OpenAI."""
        config_event = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": "You are a helpful voice assistant in a Discord voice chat called ZPT. Keep responses concise and conversational. Be friendly and engaging. You have the ability to generate images when users request them - use the generate_image tool when a user asks you to create, draw, make, or generate an image of something.",
                "voice": "alloy",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500
                },
                "tools": [
                    {
                        "type": "function",
                        "name": "generate_image",
                        "description": "Generate an image based on the user's description. Use this when a user asks to create, draw, make, generate, or design an image, picture, artwork, or visual content.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "prompt": {
                                    "type": "string",
                                    "description": "A detailed description of the image to generate. Be descriptive and include style, colors, subjects, and any specific details the user mentioned."
                                }
                            },
                            "required": ["prompt"]
                        }
                    }
                ],
                "tool_choice": "auto"
            }
        }
        
        await self._send_event(config_event)
        logger.debug("Sent session configuration to OpenAI with image generation tool")
    
    async def _send_event(self, event: Dict[str, Any]):
        """Send an event to the OpenAI WebSocket."""
        if self.websocket and self.websocket.state == WebSocketState.OPEN:
            try:
                event_type = event.get("type", "unknown")
                logger.debug(f"[DEBUG] Sending event to OpenAI: {event_type}")
                await self.websocket.send(json.dumps(event))
            except Exception as e:
                logger.error(f"Error sending event to OpenAI: {e}")
    
    async def send_audio(self, audio_data: bytes):
        """
        Send audio data to OpenAI Realtime API.
        
        Args:
            audio_data: Raw PCM audio bytes (24kHz, 16-bit, mono)
        """
        if not self.websocket or self.websocket.state != WebSocketState.OPEN:
            logger.debug("[DEBUG] Cannot send audio - WebSocket not open")
            return
        
        # Track stats
        self._stats.record_audio_sent(len(audio_data))
        
        # Encode audio to base64
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        
        event = {
            "type": "input_audio_buffer.append",
            "audio": audio_base64
        }
        
        await self._send_event(event)
    
    async def commit_audio(self):
        """Signal that audio input is complete and request a response."""
        if not self.websocket or self.websocket.state != WebSocketState.OPEN:
            return
        
        logger.debug("[DEBUG] Committing audio buffer and requesting response")
        
        # Commit the audio buffer
        await self._send_event({"type": "input_audio_buffer.commit"})
        
        # Create a response
        await self._send_event({"type": "response.create"})
    
    async def _receive_loop(self):
        """Main loop for receiving messages from OpenAI."""
        logger.debug("[DEBUG] Starting OpenAI message receive loop")
        try:
            while self._running and self.websocket:
                try:
                    message = await asyncio.wait_for(
                        self.websocket.recv(),
                        timeout=60.0
                    )
                    await self._handle_message(message)
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    logger.debug("[DEBUG] WebSocket receive timeout - continuing (keepalive)")
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.info("OpenAI WebSocket connection closed")
                    break
        except asyncio.CancelledError:
            logger.debug("Receive loop cancelled")
        except Exception as e:
            logger.error(f"Error in receive loop: {e}")
        finally:
            self._running = False
            logger.debug(f"[DEBUG] Receive loop ended. Session stats: {self._stats.get_summary()}")
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket messages from OpenAI."""
        try:
            event = json.loads(message)
            event_type = event.get("type", "")
            
            # Log all event types at debug level for troubleshooting
            logger.debug(f"[DEBUG] Received OpenAI event: {event_type} at {datetime.now().isoformat()}")
            
            if event_type == "error":
                error_details = event.get('error', {})
                logger.error(f"OpenAI Realtime API error: {error_details}")
                logger.debug(f"[DEBUG] Full error event: {json.dumps(event)}")
                
            elif event_type == "session.created":
                logger.info("OpenAI Realtime session created")
                logger.debug(f"[DEBUG] Session details: {json.dumps(event.get('session', {}))}")
                
            elif event_type == "session.updated":
                logger.info("⚙️ OpenAI Realtime session configured successfully")
                
            elif event_type == "response.created":
                logger.info("🤔 Bot is generating a response...")
                self._response_in_progress = True
                self._stats.record_response_start()
                
            elif event_type == "response.audio.delta":
                # Received audio chunk from OpenAI
                audio_base64 = event.get("delta", "")
                if audio_base64:
                    audio_data = base64.b64decode(audio_base64)
                    self._stats.record_audio_received(len(audio_data))
                    self._audio_buffer.extend(audio_data)
                    
                    # Send chunks to callback when buffer is large enough
                    while len(self._audio_buffer) >= AUDIO_BUFFER_SIZE:
                        chunk = bytes(self._audio_buffer[:AUDIO_BUFFER_SIZE])
                        del self._audio_buffer[:AUDIO_BUFFER_SIZE]
                        self.on_audio_response(chunk)
                        
            elif event_type == "response.audio.done":
                # Send any remaining audio in buffer
                if self._audio_buffer:
                    self.on_audio_response(bytes(self._audio_buffer))
                    self._audio_buffer.clear()
                logger.info("🔊 Audio response complete - sent to Discord")
                logger.debug(f"[DEBUG] Audio response complete. Stats: chunks received={self._stats.audio_chunks_received}, bytes={self._stats.audio_bytes_received}")
                
            elif event_type == "response.audio_transcript.delta":
                # Received text transcription of bot's response
                if self.on_text_response:
                    text = event.get("delta", "")
                    if text:
                        self.on_text_response(text)
                        
            elif event_type == "response.audio_transcript.done":
                # Full transcription of bot's response
                transcript = event.get("transcript", "")
                if transcript:
                    logger.info(f"🗣️ Bot said: \"{transcript}\"")
                        
            elif event_type == "conversation.item.input_audio_transcription.completed":
                # User's speech was transcribed
                transcript = event.get("transcript", "")
                if transcript:
                    logger.info(f"📝 User said: \"{transcript}\"")
                    
            elif event_type == "input_audio_buffer.speech_started":
                logger.info("🎤 Speech detected - listening to user")
                self._stats.record_speech_start()
                
            elif event_type == "input_audio_buffer.speech_stopped":
                logger.info("🔇 Speech ended - processing user input")
                logger.debug(f"[DEBUG] Speech processing started at {datetime.now().isoformat()}")
                
            elif event_type == "response.function_call_arguments.done":
                # Function call arguments are complete - execute the function
                self._stats.record_function_call(event.get("name", "unknown"))
                await self._handle_function_call(event)
                
            elif event_type == "response.done":
                logger.info("✅ Response generation complete - finished speaking")
                self._response_in_progress = False
                logger.debug(f"[DEBUG] Response complete. Current session stats: {self._stats.get_summary()}")
                
            elif event_type == "rate_limits.updated":
                logger.debug(f"[DEBUG] Rate limits updated: {event.get('rate_limits', [])}")
                
            else:
                # Log unknown event types at debug level
                logger.debug(f"[DEBUG] Unhandled event type: {event_type}")
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI message: {e}")
        except Exception as e:
            logger.error(f"Error handling OpenAI message: {e}")
    
    async def _handle_function_call(self, event: Dict[str, Any]):
        """
        Handle a function call from OpenAI.
        
        Args:
            event: The function call arguments done event
        """
        timer = VoiceDebugTimer("Function Call Handling")
        timer.start()
        
        try:
            call_id = event.get("call_id")
            name = event.get("name")
            arguments_str = event.get("arguments", "{}")
            
            if not call_id:
                logger.error("Function call missing call_id")
                return
            
            logger.info(f"🔧 Function call received: {name} (call_id: {call_id})")
            logger.debug(f"[DEBUG] Function call arguments: {arguments_str}")
            
            # Parse arguments
            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError:
                arguments = {}
                logger.warning(f"Failed to parse function arguments: {arguments_str}")
            
            timer.checkpoint("Arguments parsed")
            
            # Handle generate_image function
            if name == "generate_image":
                prompt = arguments.get("prompt", "")
                if prompt:
                    logger.info(f"🎨 Generating image with prompt: {prompt}")
                    await self._execute_image_generation(call_id, prompt)
                else:
                    # No prompt provided, send error response
                    await self._send_function_output(call_id, "Error: No prompt provided for image generation.")
            else:
                # Unknown function
                logger.warning(f"Unknown function called: {name}")
                await self._send_function_output(call_id, f"Error: Unknown function '{name}'")
            
            timer.end()
                
        except Exception as e:
            logger.error(f"Error handling function call: {e}")
            timer.end()
            if call_id:
                await self._send_function_output(call_id, f"Error executing function: {str(e)}")
    
    async def _execute_image_generation(self, call_id: str, prompt: str):
        """
        Execute image generation using the existing Gemini model.
        
        Args:
            call_id: The function call ID
            prompt: The image generation prompt
        """
        timer = VoiceDebugTimer("Image Generation")
        timer.start()
        
        try:
            # Use the existing Gemini model generator
            logger.debug(f"[DEBUG] Using model: {DEFAULT_VOICE_IMAGE_MODEL}")
            generator = get_model_generator(DEFAULT_VOICE_IMAGE_MODEL)
            timer.checkpoint("Model generator obtained")
            
            # Generate the image
            logger.debug(f"[DEBUG] Starting image generation for prompt: {prompt[:DEBUG_LOG_PROMPT_TRUNCATE_LENGTH]}...")
            generated_image, text_response, usage_metadata = await generator.generate_image_from_text(prompt)
            timer.checkpoint("Image generation API call complete")
            
            if generated_image:
                logger.info(f"✅ Image generated successfully for prompt: {prompt}")
                logger.debug(f"[DEBUG] Usage metadata: {usage_metadata}")
                
                # Notify callback that image was generated
                if self.on_image_generated:
                    self.on_image_generated(generated_image, prompt)
                    timer.checkpoint("Image callback notified")
                
                # Send success response back to OpenAI
                await self._send_function_output(
                    call_id, 
                    f"Successfully generated image based on the prompt: '{prompt}'. The image has been sent to the Discord channel."
                )
            else:
                logger.warning(f"Image generation failed for prompt: {prompt}")
                logger.debug(f"[DEBUG] Text response from failed generation: {text_response}")
                error_msg = text_response if text_response else "Failed to generate image. Please try again with a different description."
                await self._send_function_output(call_id, error_msg)
            
            timer.end()
                
        except Exception as e:
            logger.error(f"Error during image generation: {e}")
            timer.end()
            await self._send_function_output(call_id, f"Error generating image: {str(e)}")
    
    async def _send_function_output(self, call_id: str, output: str):
        """
        Send function call output back to OpenAI and request continuation.
        
        Args:
            call_id: The function call ID
            output: The function output as a string
        """
        try:
            # Send the function output
            output_event = {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output
                }
            }
            await self._send_event(output_event)
            logger.debug(f"Sent function output for call_id: {call_id}")
            
            # Request model to continue responding
            await self._send_event({"type": "response.create"})
            logger.debug("Requested response continuation after function call")
            
        except Exception as e:
            logger.error(f"Error sending function output: {e}")
    
    async def disconnect(self):
        """Close the WebSocket connection."""
        self._running = False
        
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
        
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")
            self.websocket = None
        
        logger.info("Disconnected from OpenAI Realtime API")


class VoiceConnectionManager:
    """
    Manages voice channel connections and audio streaming for Discord bots.
    Handles the full-duplex speech interaction with OpenAI's Realtime API.
    """
    
    def __init__(self):
        # Track active voice sessions per guild
        self._sessions: Dict[int, 'VoiceSession'] = {}
        
    def get_session(self, guild_id: int) -> Optional['VoiceSession']:
        """Get the voice session for a guild."""
        return self._sessions.get(guild_id)
    
    def has_active_session(self, guild_id: int) -> bool:
        """Check if a guild has an active voice session."""
        return guild_id in self._sessions
    
    async def connect(self, voice_channel: discord.VoiceChannel, text_channel: Optional[discord.TextChannel] = None) -> tuple[Optional['VoiceSession'], Optional[str]]:
        """
        Connect to a voice channel and start a new voice session.
        
        Args:
            voice_channel: The Discord voice channel to join
            text_channel: Optional text channel to post generated images to
            
        Returns:
            Tuple of (VoiceSession, None) if successful, or (None, error_reason) on failure
        """
        timer = VoiceDebugTimer("Voice Channel Connection")
        timer.start()
        
        guild_id = voice_channel.guild.id
        
        # Check if already connected
        if guild_id in self._sessions:
            logger.warning(f"Already connected to a voice channel in guild {guild_id}")
            return self._sessions[guild_id], None
        
        try:
            # Connect to voice channel
            logger.info(f"🎙️ Connecting to voice channel '{voice_channel.name}' (ID: {voice_channel.id}) in guild {guild_id}")
            logger.debug(f"[DEBUG] Voice receive extension available: {VOICE_RECV_AVAILABLE}")
            
            # Use VoiceRecvClient if available for voice input support
            if VOICE_RECV_AVAILABLE:
                logger.info("📥 Voice receive extension available - enabling voice input")
                voice_client = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
            else:
                logger.warning("⚠️ Voice receive extension not available - voice input disabled")
                voice_client = await voice_channel.connect()
            
            timer.checkpoint("Discord voice channel connected")
            logger.info(f"✅ Successfully connected to Discord voice channel '{voice_channel.name}'")
            
            # Create voice session with text channel for image posting
            session = VoiceSession(voice_client, self, text_channel)
            self._sessions[guild_id] = session
            
            # Start the session (connects to OpenAI and starts audio processing)
            logger.info("🚀 Starting voice session and OpenAI Realtime API connection...")
            success, error_reason = await session.start()
            timer.checkpoint("Voice session start attempt complete")
            
            if success:
                timer.end()
                logger.info(f"✅ Voice session fully started in guild {guild_id}")
                return session, None
            else:
                # Failed to start session, cleanup
                timer.end()
                logger.error(f"❌ Voice session failed to start in guild {guild_id}: {error_reason}")
                await self.disconnect(guild_id)
                return None, error_reason
                
        except discord.ClientException as e:
            error_msg = f"Discord client error: {e}"
            timer.end()
            logger.error(f"❌ {error_msg}")
            return None, error_msg
        except discord.opus.OpusNotLoaded as e:
            error_msg = f"Opus library not loaded (required for voice): {e}"
            timer.end()
            logger.error(f"❌ {error_msg}")
            return None, error_msg
        except Exception as e:
            error_msg = f"Voice channel connection error: {type(e).__name__}: {e}"
            timer.end()
            logger.error(f"❌ {error_msg}")
            return None, error_msg
    
    async def disconnect(self, guild_id: int) -> bool:
        """
        Disconnect from voice channel and cleanup session.
        
        Args:
            guild_id: The Discord guild ID
            
        Returns:
            True if disconnected successfully, False otherwise
        """
        logger.debug(f"[DEBUG] Disconnecting voice session for guild {guild_id}")
        session = self._sessions.pop(guild_id, None)
        if session:
            await session.stop()
            logger.debug(f"[DEBUG] Voice session disconnected for guild {guild_id}")
            return True
        logger.debug(f"[DEBUG] No active session found for guild {guild_id}")
        return False
    
    async def disconnect_all(self):
        """Disconnect from all voice channels."""
        logger.debug(f"[DEBUG] Disconnecting all voice sessions ({len(self._sessions)} active)")
        guild_ids = list(self._sessions.keys())
        for guild_id in guild_ids:
            await self.disconnect(guild_id)


class StreamingAudioSource(discord.AudioSource):
    """Audio source that streams audio from a queue."""
    
    def __init__(self):
        self._audio_queue: deque = deque()
        self._current_chunk: Optional[bytes] = None
        self._chunk_position = 0
        self._frame_size = 3840  # 20ms of audio at 48kHz stereo (960 samples * 2 channels * 2 bytes)
        self._is_playing = False
        
    def add_audio(self, audio_data: bytes):
        """Add audio data to the playback queue."""
        self._audio_queue.append(audio_data)
        self._is_playing = True
        
    def read(self) -> bytes:
        """Read the next frame of audio data."""
        # Try to get more data if needed
        while self._current_chunk is None or self._chunk_position >= len(self._current_chunk):
            if self._audio_queue:
                self._current_chunk = self._audio_queue.popleft()
                self._chunk_position = 0
            else:
                # No more audio, return silence
                self._is_playing = False
                return b'\x00' * self._frame_size
        
        # Extract frame from current chunk
        end_pos = min(self._chunk_position + self._frame_size, len(self._current_chunk))
        frame = self._current_chunk[self._chunk_position:end_pos]
        self._chunk_position = end_pos
        
        # Pad with silence if needed
        if len(frame) < self._frame_size:
            frame += b'\x00' * (self._frame_size - len(frame))
        
        return frame
    
    def is_opus(self) -> bool:
        """Return False since we're providing raw PCM audio."""
        return False
    
    @property
    def is_playing(self) -> bool:
        """Check if audio is currently being played."""
        return self._is_playing or bool(self._audio_queue)
    
    def cleanup(self):
        """Clean up the audio source."""
        self._audio_queue.clear()
        self._current_chunk = None
        self._chunk_position = 0


class OpenAIVoiceSink(voice_recv.AudioSink if VOICE_RECV_AVAILABLE else object):
    """
    Audio sink that receives voice data from Discord and streams it to OpenAI.
    Implements the discord-ext-voice-recv AudioSink interface.
    """
    
    def __init__(self, voice_session: 'VoiceSession'):
        """
        Initialize the OpenAI voice sink.
        
        Args:
            voice_session: The VoiceSession instance to send audio to
        """
        self._voice_session = voice_session
        self._loop = asyncio.get_event_loop()
        # Audio buffer for batching chunks to reduce cross-thread calls
        self._audio_buffer = bytearray()
        self._buffer_lock = asyncio.Lock()
        # Buffer threshold: ~100ms of audio at 24kHz mono (2400 samples * 2 bytes)
        self._buffer_threshold = 4800
        
    def wants_opus(self) -> bool:
        """Return False - we want decoded PCM audio, not Opus."""
        return False
    
    def write(self, user: discord.User, data: 'voice_recv.VoiceData'):
        """
        Handle incoming voice data from a user.
        
        This method is called by discord-ext-voice-recv when audio is received.
        The audio is in Discord format (48kHz, 16-bit, stereo PCM).
        
        Args:
            user: The Discord user who is speaking
            data: The voice data containing PCM audio
        """
        if not self._voice_session.openai_session:
            return
        
        try:
            # Get the PCM audio data (48kHz, 16-bit, stereo)
            pcm_data = data.pcm
            
            if pcm_data:
                # Resample from Discord format (48kHz stereo) to OpenAI format (24kHz mono)
                # Using the static method directly for efficiency
                resampled_audio = AudioResampler.resample_48k_stereo_to_24k_mono(pcm_data)
                
                if resampled_audio:
                    # Add to buffer
                    self._audio_buffer.extend(resampled_audio)
                    
                    # Send when buffer reaches threshold to reduce cross-thread calls
                    if len(self._audio_buffer) >= self._buffer_threshold:
                        audio_to_send = bytes(self._audio_buffer)
                        self._audio_buffer.clear()
                        
                        # Schedule the async send_audio call in the event loop
                        asyncio.run_coroutine_threadsafe(
                            self._voice_session.openai_session.send_audio(audio_to_send),
                            self._loop
                        )
        except Exception as e:
            logger.error(f"Error processing voice data from {user}: {e}")
    
    def cleanup(self):
        """Clean up the audio sink and flush any remaining audio."""
        # Flush any remaining buffered audio
        if self._audio_buffer and self._voice_session.openai_session:
            try:
                audio_to_send = bytes(self._audio_buffer)
                self._audio_buffer.clear()
                asyncio.run_coroutine_threadsafe(
                    self._voice_session.openai_session.send_audio(audio_to_send),
                    self._loop
                )
            except Exception as e:
                logger.warning(f"Error flushing audio buffer during cleanup: {e}")



class VoiceSession:
    """
    Represents an active voice chat session with OpenAI Realtime API.
    Handles receiving audio from Discord and sending responses back.
    """
    
    def __init__(self, voice_client: VoiceClient, manager: VoiceConnectionManager, text_channel: Optional[discord.TextChannel] = None):
        self.voice_client = voice_client
        self.manager = manager
        self.text_channel = text_channel  # Channel to post generated images to
        self.openai_session: Optional[OpenAIRealtimeSession] = None
        self._running = False
        self._audio_source: Optional[StreamingAudioSource] = None
        self._audio_sink: Optional['OpenAIVoiceSink'] = None
        self._listen_task: Optional[asyncio.Task] = None
        self._pending_images: List[Tuple[Any, str]] = []  # Queue for (image, prompt) tuples
        
    @property
    def guild_id(self) -> int:
        """Get the guild ID for this session."""
        return self.voice_client.guild.id
    
    @property
    def channel(self) -> discord.VoiceChannel:
        """Get the voice channel for this session."""
        return self.voice_client.channel
        
    async def start(self) -> tuple[bool, Optional[str]]:
        """
        Start the voice session.
        Connects to OpenAI and begins audio processing.
        
        Returns:
            Tuple of (True, None) if started successfully, or (False, error_reason) on failure
        """
        timer = VoiceDebugTimer("Voice Session Start")
        timer.start()
        
        # Create audio source for playback
        self._audio_source = StreamingAudioSource()
        logger.debug("[DEBUG] Audio source created")
        
        # Create OpenAI session with callback for audio responses and image generation
        self.openai_session = OpenAIRealtimeSession(
            on_audio_response=self._handle_openai_audio,
            on_image_generated=self._handle_image_generated
        )
        logger.debug("[DEBUG] OpenAI session instance created")
        timer.checkpoint("Session instances created")
        
        # Connect to OpenAI
        logger.info("🔗 Connecting to OpenAI Realtime API...")
        success, error_reason = await self.openai_session.connect()
        timer.checkpoint("OpenAI connection attempt complete")
        
        if not success:
            logger.error(f"❌ Failed to connect to OpenAI Realtime API: {error_reason}")
            timer.end()
            return False, error_reason
        
        logger.info("✅ Successfully connected to OpenAI Realtime API")
        self._running = True
        
        # Start listening for Discord audio
        self._listen_task = asyncio.create_task(self._listen_loop())
        logger.debug("[DEBUG] Listen loop task created")
        timer.checkpoint("Listen loop started")
        
        # Start playing audio source
        try:
            self.voice_client.play(self._audio_source)
            logger.info("🔊 Audio playback initialized - ready to play bot responses")
            timer.checkpoint("Audio playback started")
        except Exception as e:
            error_msg = f"Audio playback error: {type(e).__name__}: {e}"
            logger.error(f"❌ {error_msg}")
            timer.end()
            return False, error_msg
        
        timer.end()
        logger.debug(f"[DEBUG] Voice session fully started at {datetime.now().isoformat()}")
        return True, None
    
    def _handle_openai_audio(self, audio_data: bytes):
        """
        Handle audio data received from OpenAI.
        Resamples and queues for playback.
        
        Args:
            audio_data: Raw PCM audio (24kHz, 16-bit, mono)
        """
        # Resample to Discord format (48kHz stereo) using static method
        discord_audio = AudioResampler.resample_24k_mono_to_48k_stereo(audio_data)
        
        # Add to playback queue
        if self._audio_source:
            self._audio_source.add_audio(discord_audio)
    
    def _handle_image_generated(self, image: Any, prompt: str):
        """
        Handle an image that was generated by the voice assistant.
        Queues the image for sending to the text channel.
        
        Args:
            image: The generated PIL Image
            prompt: The prompt used to generate the image
        """
        logger.debug(f"[DEBUG] Image generated callback triggered for prompt: {prompt[:DEBUG_LOG_PROMPT_TRUNCATE_LENGTH]}...")
        if image and self.text_channel:
            # Queue the image for sending (will be processed in the event loop)
            self._pending_images.append((image, prompt))
            # Schedule the async send operation
            asyncio.create_task(self._send_pending_images())
    
    async def _send_pending_images(self):
        """Send any pending generated images to the text channel."""
        while self._pending_images:
            image, prompt = self._pending_images.pop(0)
            try:
                logger.debug(f"[DEBUG] Sending generated image to Discord channel")
                # Save image to buffer
                img_buffer = io.BytesIO()
                image.save(img_buffer, format='PNG')
                img_buffer.seek(0)
                
                # Create Discord file
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"voice_generated_{timestamp}.png"
                
                # Send to text channel
                await self.text_channel.send(
                    content=f"🎨 **Voice-generated image**\n*Prompt: {prompt}*",
                    file=discord.File(img_buffer, filename=filename)
                )
                logger.info(f"📤 Sent generated image to text channel: {prompt[:DEBUG_LOG_PROMPT_TRUNCATE_LENGTH]}...")
                
            except Exception as e:
                logger.error(f"Error sending generated image to channel: {e}")
    
    async def _listen_loop(self):
        """
        Main loop for receiving audio from Discord voice channel.
        
        Uses discord-ext-voice-recv extension when available to capture voice input
        and stream it to OpenAI Realtime API.
        """
        try:
            logger.info("🎧 Voice session active - connected to OpenAI Realtime API")
            logger.debug(f"[DEBUG] Listen loop started at {datetime.now().isoformat()}")
            
            # Check if voice receive is available and voice client supports it
            if VOICE_RECV_AVAILABLE and isinstance(self.voice_client, voice_recv.VoiceRecvClient):
                logger.info("✅ Voice INPUT enabled - bot can listen and respond")
                logger.debug("[DEBUG] VoiceRecvClient is active, creating audio sink")
                
                # Create and start the audio sink for receiving voice
                self._audio_sink = OpenAIVoiceSink(self)
                self.voice_client.listen(self._audio_sink)
                logger.info("🎤 Now listening for voice input from users")
                logger.debug("[DEBUG] Audio sink attached to voice client")
                
                # Keep the session alive while listening
                loop_count = 0
                while self._running:
                    await asyncio.sleep(0.1)
                    loop_count += 1
                    # Log periodic heartbeat
                    if loop_count % DEBUG_HEARTBEAT_INTERVAL_LOOPS == 0:
                        logger.debug(f"[DEBUG] Voice session heartbeat - running for {loop_count * 0.1:.0f}s")
                    
            else:
                # Voice receive not available - playback only mode
                if not VOICE_RECV_AVAILABLE:
                    logger.warning("⚠️ Voice INPUT is not available - discord-ext-voice-recv not installed")
                    logger.info("📋 To enable voice input: pip install discord-ext-voice-recv")
                else:
                    logger.warning("⚠️ Voice INPUT is not available - VoiceRecvClient not active")
                
                logger.info("🔊 Bot can only PLAY audio responses, not LISTEN to users")
                logger.debug("[DEBUG] Running in playback-only mode")
                
                # Keep the session alive in playback-only mode
                while self._running:
                    await asyncio.sleep(0.1)
                
        except asyncio.CancelledError:
            logger.debug("[DEBUG] Listen loop cancelled")
        except Exception as e:
            logger.error(f"Error in listen loop: {e}")
        finally:
            logger.debug(f"[DEBUG] Listen loop ended at {datetime.now().isoformat()}")
    
    async def stop(self):
        """Stop the voice session and cleanup."""
        timer = VoiceDebugTimer("Voice Session Stop")
        timer.start()
        
        logger.info(f"🔌 Stopping voice session in guild {self.guild_id}...")
        self._running = False
        
        # Stop listening for voice input if active
        if VOICE_RECV_AVAILABLE and isinstance(self.voice_client, voice_recv.VoiceRecvClient):
            try:
                self.voice_client.stop_listening()
                logger.info("🔇 Stopped listening for voice input")
                timer.checkpoint("Voice listening stopped")
            except Exception as e:
                logger.warning(f"Error stopping voice listening: {e}")
        
        # Cleanup audio sink
        if self._audio_sink:
            self._audio_sink.cleanup()
            self._audio_sink = None
            logger.debug("[DEBUG] Audio sink cleaned up")
        
        # Cancel listen task
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None
            timer.checkpoint("Listen task cancelled")
        
        # Disconnect from OpenAI
        if self.openai_session:
            logger.info("🔗 Disconnecting from OpenAI Realtime API...")
            await self.openai_session.disconnect()
            self.openai_session = None
            timer.checkpoint("OpenAI disconnected")
        
        # Stop audio playback
        if self.voice_client.is_playing():
            self.voice_client.stop()
            logger.debug("[DEBUG] Audio playback stopped")
        
        # Cleanup audio source
        if self._audio_source:
            self._audio_source.cleanup()
            self._audio_source = None
            logger.debug("[DEBUG] Audio source cleaned up")
        
        # Disconnect from voice channel
        if self.voice_client.is_connected():
            await self.voice_client.disconnect()
            timer.checkpoint("Discord voice disconnected")
        
        timer.end()
        logger.info(f"👋 Voice session stopped in guild {self.guild_id}")


# Global voice connection manager instance
voice_manager = VoiceConnectionManager()
