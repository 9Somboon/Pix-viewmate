import sys
import signal
from functools import partial
from PyQt6.QtWidgets import QApplication
from main_window import ImageFilterApp

def signal_handler(window, signum, frame):
    """Handle SIGINT signal to close the application gracefully."""
    print("Received interrupt signal. Closing application gracefully...")
    window.close()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ImageFilterApp()
    window.show()
    
    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, partial(signal_handler, window))
    
    sys.exit(app.exec())