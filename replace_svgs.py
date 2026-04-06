import re

with open(
    r"C:\Users\syste\Desktop\Melikhan\Web\Web Projeler\web_ar-main\templates\view.html",
    "r",
    encoding="utf-8",
) as f:
    content = f.read()

# SVG to Lucide icon mapping based on content analysis
svg_replacements = [
    # Pattern: (regex pattern, lucide icon name)
    # Calendar icon (in stats)
    (
        r'<svg[^>]*width="14"[^>]*height="14"[^>]*>.*?<rect[^>]*rx="2"[^>]*ry="2".*?/>.*?<line[^>]*x1="16"[^>]*y1="2".*?/>.*?<line[^>]*x1="8"[^>]*y1="2".*?/>.*?<line[^>]*x1="3"[^>]*y1="10".*?/>.*?</svg>',
        "calendar",
    ),
    # Download icon
    (
        r'<svg[^>]*width="14"[^>]*height="14"[^>]*>.*?<path[^>]*d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4".*?/>.*?<polyline[^>]*points="7 10 12 15 17 10".*?/>.*?<line[^>]*x1="12"[^>]*y1="15".*?/>.*?</svg>',
        "download",
    ),
    # Upload icon
    (
        r'<svg[^>]*width="14"[^>]*height="14"[^>]*>.*?<path[^>]*d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4".*?/>.*?<polyline[^>]*points="17 8 12 3 7 8".*?/>.*?<line[^>]*x1="12"[^>]*y1="3".*?/>.*?</svg>',
        "upload",
    ),
    # Eye icon
    (
        r'<svg[^>]*width="14"[^>]*height="14"[^>]*>.*?<path[^>]*d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z".*?/>.*?<circle[^>]*cx="12"[^>]*cy="12"[^>]*r="3".*?/>.*?</svg>',
        "eye",
    ),
    # Menu/hamburger (in nav button and mobile fab)
    (
        r'<svg[^>]*class="mr-2"[^>]*width="16"[^>]*height="16"[^>]*>.*?<path[^>]*d="M4 6h16M4 12h16M4 18h16".*?/>.*?</svg>',
        "menu",
    ),
    (
        r'<svg[^>]*class="w-4 h-4"[^>]*>.*?<path[^>]*d="M4 6h16M4 12h16M4 18h10".*?/>.*?</svg>',
        "menu",
    ),
    (
        r'<svg[^>]*class="pill-icon"[^>]*>.*?<path[^>]*d="M4 6h16M4 12h16M4 18h16".*?/>.*?</svg>',
        "menu",
    ),
    # Close X (in QR modal)
    (
        r'<svg[^>]*class="h-6 w-6"[^>]*>.*?<path[^>]*d="M6 18L18 6M6 6l12 12".*?/>.*?</svg>',
        "x",
    ),
    # Monitor (AR button)
    (
        r'<svg[^>]*class="w-3.5 h-3.5"[^>]*>.*?<path[^>]*d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z".*?/>.*?</svg>',
        "monitor",
    ),
    # QR code
    (
        r'<svg[^>]*xmlns="http://www.w3.org/2000/svg"[^>]*class="w-3.5 h-3.5"[^>]*>.*?<rect[^>]*x="3"[^>]*y="3"[^>]*width="7"[^>]*height="7".*?/>.*?<rect[^>]*x="14"[^>]*y="3"[^>]*width="7"[^>]*height="7".*?/>.*?<rect[^>]*x="14"[^>]*y="14"[^>]*width="7"[^>]*height="7".*?/>.*?<rect[^>]*x="3"[^>]*y="14"[^>]*width="7"[^>]*height="7".*?/>.*?</svg>',
        "qr-code",
    ),
    # Thumbs up (like)
    (
        r'<svg[^>]*xmlns="http://www.w3.org/2000/svg"[^>]*class="w-3.5 h-3.5"[^>]*>.*?<path[^>]*d="M14 9V5a3 3 0 00-6 0v4".*?/>.*?<path[^>]*d="M5 9h14l1 12H4L5 9z".*?/>.*?</svg>',
        "thumbs-up",
    ),
    # Bookmark (save)
    (
        r'<svg[^>]*xmlns="http://www.w3.org/2000/svg"[^>]*class="w-3.5 h-3.5"[^>]*>.*?<path[^>]*d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z".*?/>.*?</svg>',
        "bookmark",
    ),
    # Share
    (
        r'<svg[^>]*xmlns="http://www.w3.org/2000/svg"[^>]*class="w-3.5 h-3.5"[^>]*>.*?<circle[^>]*cx="18"[^>]*cy="5"[^>]*r="3".*?/>.*?<circle[^>]*cx="6"[^>]*cy="12"[^>]*r="3".*?/>.*?<circle[^>]*cx="18"[^>]*cy="19"[^>]*r="3".*?/>.*?<line[^>]*x1="8.59"[^>]*y1="13.51".*?/>.*?<line[^>]*x1="15.41"[^>]*y1="6.51".*?/>.*?</svg>',
        "share-2",
    ),
    # Camera (screenshot)
    (
        r'<svg[^>]*xmlns="http://www.w3.org/2000/svg"[^>]*class="w-3.5 h-3.5"[^>]*>.*?<path[^>]*d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z".*?/>.*?<circle[^>]*cx="12"[^>]*cy="13"[^>]*r="4".*?/>.*?</svg>',
        "camera",
    ),
    # Info
    (
        r'<svg[^>]*xmlns="http://www.w3.org/2000/svg"[^>]*class="w-3.5 h-3.5"[^>]*>.*?<circle[^>]*cx="12"[^>]*cy="12"[^>]*r="10".*?/>.*?<line[^>]*x1="12"[^>]*y1="16".*?/>.*?<line[^>]*x1="12"[^>]*y1="8".*?/>.*?</svg>',
        "info",
    ),
    # Maximize (fullscreen)
    (
        r'<svg[^>]*xmlns="http://www.w3.org/2000/svg"[^>]*class="w-3.5 h-3.5"[^>]*>.*?<path[^>]*d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4".*?/>.*?</svg>',
        "maximize",
    ),
    # Moon
    (
        r'<svg[^>]*class="w-3.5 h-3.5 opacity-100 dark:opacity-0"[^>]*>.*?<path[^>]*d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 009.354-5.646z".*?/>.*?</svg>',
        "moon",
    ),
    # Sun
    (
        r'<svg[^>]*class="w-3.5 h-3.5 opacity-0 dark:opacity-100 absolute"[^>]*>.*?<path[^>]*d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z".*?/>.*?</svg>',
        "sun",
    ),
    # Chevron right (sidebar toggle)
    (
        r'<svg[^>]*id="sidebarToggleIcon"[^>]*>.*?<path[^>]*d="M9 18l6-6-6-6".*?/>.*?</svg>',
        "chevron-right",
    ),
    # Refresh (reset camera)
    (
        r'<svg[^>]*class="w-3.5 h-3.5"[^>]*>.*?<path[^>]*d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15".*?/>.*?</svg>',
        "refresh-cw",
    ),
    # Play
    (
        r'<svg[^>]*class="w-4 h-4"[^>]*>.*?<path[^>]*d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z".*?/>.*?<path[^>]*d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z".*?/>.*?</svg>',
        "play",
    ),
    # Chevron down (panel icons)
    (
        r'<svg[^>]*id="animationContentIcon"[^>]*>.*?<path[^>]*d="M19 9l-7 7-7-7".*?/>.*?</svg>',
        "chevron-down",
    ),
    (
        r'<svg[^>]*id="materialPanelIcon"[^>]*>.*?<path[^>]*d="M19 9l-7 7-7-7".*?/>.*?</svg>',
        "chevron-down",
    ),
    (
        r'<svg[^>]*id="transformPanelIcon"[^>]*>.*?<path[^>]*d="M19 9l-7 7-7-7".*?/>.*?</svg>',
        "chevron-down",
    ),
    (
        r'<svg[^>]*id="annotationsPanelIcon"[^>]*>.*?<path[^>]*d="M19 9l-7 7-7-7".*?/>.*?</svg>',
        "chevron-down",
    ),
    (
        r'<svg[^>]*id="slicerPanelIcon"[^>]*>.*?<path[^>]*d="M19 9l-7 7-7-7".*?/>.*?</svg>',
        "chevron-down",
    ),
    # Scissors (slicer)
    (
        r'<svg[^>]*class="w-4 h-4"[^>]*>.*?<path[^>]*d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879M12 12L9.121 9.121m0 5.758L5 19m0-14l4.121 4.121".*?/>.*?</svg>',
        "scissors",
    ),
    # Check (save)
    (
        r'<svg[^>]*class="w-4 h-4"[^>]*>.*?<path[^>]*d="M5 13l4 4L19 7".*?/>.*?</svg>',
        "check",
    ),
    # Login icon
    (
        r'<svg[^>]*style="width:0.85rem;height:0.85rem;margin-right:0.35rem;"[^>]*>.*?<path[^>]*d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1".*?/>.*?</svg>',
        "log-in",
    ),
    # Lightning (AR modal phone icon)
    (
        r'<svg[^>]*class="w-32 h-32[^"]*"[^>]*>.*?<path[^>]*d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z".*?/>.*?</svg>',
        "smartphone",
    ),
    # File (info modal - file name)
    (
        r'<svg[^>]*class="w-5 h-5 mr-3 mt-0.5 text-gray-500 dark:text-gray-400"[^>]*>.*?<path[^>]*d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z".*?/>.*?<polyline[^>]*points="13 2 13 9 20 9".*?/>.*?</svg>',
        "file",
    ),
    # Image (info modal - file type)
    (
        r'<svg[^>]*class="w-5 h-5 mr-3 mt-0.5 text-gray-500 dark:text-gray-400"[^>]*>.*?<rect[^>]*x="3"[^>]*y="3"[^>]*width="18"[^>]*height="18"[^>]*rx="2"[^>]*ry="2".*?/>.*?<circle[^>]*cx="8.5"[^>]*cy="8.5"[^>]*r="1.5".*?/>.*?<polyline[^>]*points="21 15 16 10 5 21".*?/>.*?</svg>',
        "image",
    ),
    # Package (info modal - file size)
    (
        r'<svg[^>]*class="w-5 h-5 mr-3 mt-0.5 text-gray-500 dark:text-gray-400"[^>]*>.*?<path[^>]*d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z".*?/>.*?</svg>',
        "package",
    ),
    # Calendar (info modal - upload date)
    (
        r'<svg[^>]*class="w-5 h-5 mr-3 mt-0.5 text-gray-500 dark:text-gray-400"[^>]*>.*?<rect[^>]*x="3"[^>]*y="4"[^>]*width="18"[^>]*height="18"[^>]*rx="2"[^>]*ry="2".*?/>.*?<line[^>]*x1="16"[^>]*y1="2".*?/>.*?<line[^>]*x1="8"[^>]*y1="2".*?/>.*?<line[^>]*x1="3"[^>]*y1="10".*?/>.*?</svg>',
        "calendar",
    ),
    # Link (info modal - model ID)
    (
        r'<svg[^>]*class="w-5 h-5 mr-3 mt-0.5 text-gray-500 dark:text-gray-400"[^>]*>.*?<path[^>]*d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71".*?/>.*?<path[^>]*d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71".*?/>.*?</svg>',
        "link",
    ),
    # Zap (info modal - vertices)
    (
        r'<svg[^>]*class="w-5 h-5 mr-3 mt-0.5 text-gray-500 dark:text-gray-400"[^>]*>.*?<circle[^>]*cx="12"[^>]*cy="12"[^>]*r="3".*?/>.*?<circle[^>]*cx="12"[^>]*cy="5"[^>]*r="1".*?/>.*?<circle[^>]*cx="19"[^>]*cy="12"[^>]*r="1".*?/>.*?<circle[^>]*cx="12"[^>]*cy="19"[^>]*r="1".*?/>.*?<circle[^>]*cx="5"[^>]*cy="12"[^>]*r="1".*?/>.*?</svg>',
        "zap",
    ),
    # Layers (info modal - faces)
    (
        r'<svg[^>]*class="w-5 h-5 mr-3 mt-0.5 text-gray-500 dark:text-gray-400"[^>]*>.*?<polygon[^>]*points="12 2 2 7 12 12 22 7 12 2".*?/>.*?<polyline[^>]*points="2 17 12 22 22 17".*?/>.*?<polyline[^>]*points="2 12 12 17 22 12".*?/>.*?</svg>',
        "layers",
    ),
    # Palette (info modal - color)
    (
        r'<svg[^>]*class="w-5 h-5 mr-3 mt-0.5 text-gray-500 dark:text-gray-400"[^>]*>.*?<circle[^>]*cx="12"[^>]*cy="12"[^>]*r="10".*?/>.*?</svg>',
        "palette",
    ),
    # Grid (info modal - dimensions)
    (
        r'<svg[^>]*class="w-5 h-5 mr-3 mt-0.5 text-gray-500 dark:text-gray-400"[^>]*>.*?<rect[^>]*x="3"[^>]*y="3"[^>]*width="18"[^>]*height="18"[^>]*rx="2"[^>]*ry="2".*?/>.*?<path[^>]*d="M3 9h18".*?/>.*?<path[^>]*d="M9 21V9".*?/>.*?</svg>',
        "grid",
    ),
    # Lightning (info modal header)
    (
        r'<svg[^>]*class="w-5 h-5 mr-2"[^>]*>.*?<path[^>]*d="M13 2L3 14h9l-1 8 10-12h-9l1-8z".*?/>.*?</svg>',
        "zap",
    ),
    # X close (info modal close)
    (
        r'<svg[^>]*class="w-6 h-6"[^>]*>.*?<line[^>]*x1="18"[^>]*y1="6".*?/>.*?<line[^>]*x1="6"[^>]*y1="6".*?/>.*?<line[^>]*x1="18"[^>]*y1="18".*?/>.*?<line[^>]*x1="6"[^>]*y1="18".*?/>.*?</svg>',
        "x",
    ),
    # Spinner (loading)
    (
        r'<svg[^>]*id="slicerSpinner"[^>]*>.*?<circle[^>]*class="opacity-25"[^>]*cx="12"[^>]*cy="12"[^>]*r="10"[^>]*stroke="currentColor"[^>]*stroke-width="4".*?/>.*?<path[^>]*class="opacity-75"[^>]*fill="currentColor"[^>]*d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z".*?/>.*?</svg>',
        "loader-2",
    ),
    # Check circle (info note)
    (
        r'<svg[^>]*class="w-4 h-4 flex-shrink-0 mt-0.5"[^>]*>.*?<path[^>]*fill-rule="evenodd"[^>]*d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z".*?/>.*?</svg>',
        "check-circle",
    ),
    # Trash (delete view/hotspot)
    (
        r'<svg[^>]*class="w-3 h-3"[^>]*>.*?<path[^>]*d="M6 18L18 6M6 6l12 12".*?/>.*?</svg>',
        "x",
    ),
    # Spinner in save button
    (
        r'<svg[^>]*class="animate-spin h-4 w-4 text-white"[^>]*>.*?<circle[^>]*class="opacity-25"[^>]*cx="12"[^>]*cy="12"[^>]*r="10"[^>]*stroke="currentColor"[^>]*stroke-width="4".*?/>.*?<path[^>]*class="opacity-75"[^>]*fill="currentColor"[^>]*d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z".*?/>.*?</svg>',
        "loader-2",
    ),
    # Spinner in load versions
    (
        r'<svg[^>]*class="animate-spin h-6 w-6 mx-auto text-gray-400"[^>]*>.*?<circle[^>]*class="opacity-25"[^>]*cx="12"[^>]*cy="12"[^>]*r="10"[^>]*stroke="currentColor"[^>]*stroke-width="4".*?/>.*?<path[^>]*class="opacity-75"[^>]*fill="currentColor"[^>]*d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z".*?/>.*?</svg>',
        "loader-2",
    ),
]

# Replace SVGs with Lucide icons
replaced_count = 0
for pattern, icon_name in svg_replacements:
    matches = re.findall(pattern, content, re.DOTALL)
    if matches:
        replacement = f'<i data-lucide="{icon_name}"></i>'
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
        replaced_count += len(matches)
        print(f'Replaced {len(matches)} SVG(s) with "{icon_name}"')

# Also handle any remaining simple SVGs that might have been missed
# Generic SVG replacement for any remaining ones
remaining_svgs = re.findall(r"<svg[^>]*>.*?</svg>", content, re.DOTALL)
if remaining_svgs:
    print(f"\nRemaining SVGs ({len(remaining_svgs)}):")
    for svg in remaining_svgs[:5]:  # Show first 5
        print(f"  - {svg[:100]}...")

print(f"\nTotal SVGs replaced: {replaced_count}")

# Save the file
with open(
    r"C:\Users\syste\Desktop\Melikhan\Web\Web Projeler\web_ar-main\templates\view.html",
    "w",
    encoding="utf-8",
) as f:
    f.write(content)

print(f"\nFile saved. New size: {len(content)} chars")
