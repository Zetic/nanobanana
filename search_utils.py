import logging
from datetime import datetime
from typing import List, Dict, Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import config

logger = logging.getLogger(__name__)

class NewsSearcher:
    """Handles Google Custom Search for news content."""
    
    def __init__(self):
        if not config.GOOGLE_SEARCH_API_KEY:
            raise ValueError("GOOGLE_SEARCH_API_KEY not found in environment variables")
        if not config.GOOGLE_SEARCH_ENGINE_ID:
            raise ValueError("GOOGLE_SEARCH_ENGINE_ID not found in environment variables")
        
        self.api_key = config.GOOGLE_SEARCH_API_KEY
        self.search_engine_id = config.GOOGLE_SEARCH_ENGINE_ID
        self.service = build("customsearch", "v1", developerKey=self.api_key)
    
    async def search_today_news(self, num_results: int = 5) -> Optional[List[Dict]]:
        """
        Search for today's biggest news stories.
        Returns a list of news articles with title, snippet, and link.
        """
        try:
            # Get today's date for the search query
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Search query focused on today's biggest news
            query = f"biggest news today {today} breaking news headlines"
            
            # Perform the search
            result = self.service.cse().list(
                q=query,
                cx=self.search_engine_id,
                num=num_results,
                sort="date:d",  # Sort by date descending
                siteSearch="",  # Can be customized to specific news sites if needed
                safe="medium"
            ).execute()
            
            news_items = []
            if 'items' in result:
                for item in result['items']:
                    news_item = {
                        'title': item.get('title', ''),
                        'snippet': item.get('snippet', ''),
                        'link': item.get('link', ''),
                        'source': item.get('displayLink', '')
                    }
                    news_items.append(news_item)
            
            logger.info(f"Found {len(news_items)} news items for today")
            return news_items
            
        except HttpError as e:
            logger.error(f"Google Search API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error searching for today's news: {e}")
            return None
    
    def format_news_for_image_prompt(self, news_items: List[Dict]) -> str:
        """
        Format news items into a descriptive prompt for image generation.
        """
        if not news_items:
            return "Create an artistic image depicting today's world news and current events"
        
        # Take the top 3 most relevant news items
        top_news = news_items[:3]
        
        # Create a descriptive prompt focusing on the main themes
        prompt_parts = [
            "Create a compelling artistic image that depicts today's biggest news stories:"
        ]
        
        for i, news in enumerate(top_news, 1):
            title = news.get('title', '').strip()
            snippet = news.get('snippet', '').strip()
            
            # Combine title and snippet for context
            story_text = f"{title}. {snippet}"[:150]  # Limit length
            prompt_parts.append(f"{i}. {story_text}")
        
        prompt_parts.append(
            "Combine these news themes into a single, visually striking and artistic image "
            "that captures the essence of today's major events. Use symbolic, metaphorical, "
            "and artistic elements rather than literal representations."
        )
        
        final_prompt = "\n".join(prompt_parts)
        logger.info(f"Generated image prompt from news: {final_prompt[:200]}...")
        
        return final_prompt

# Global instance
news_searcher = None

def get_news_searcher():
    """Get or create the news searcher instance."""
    global news_searcher
    if news_searcher is None:
        news_searcher = NewsSearcher()
    return news_searcher