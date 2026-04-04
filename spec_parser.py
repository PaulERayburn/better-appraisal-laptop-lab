"""
Shared spec parsing utilities for the Canada Tech Deal Tracker.

Extracted from app.py — provides spec extraction for laptops, desktops,
RAM, CPUs, and other tech components.
"""

import re


def parse_size(size_str):
    """Parse storage/RAM strings like '16GB', '1TB', '512GB' into GB as integer."""
    if not size_str:
        return 0
    size_str = str(size_str).upper().replace(" ", "")

    try:
        if "TB" in size_str:
            match = re.search(r'(\d+(?:\.\d+)?)', size_str)
            if match:
                return int(float(match.group(1)) * 1024)
        if "GB" in size_str:
            match = re.search(r'(\d+(?:\.\d+)?)', size_str)
            if match:
                return int(float(match.group(1)))
    except (ValueError, AttributeError):
        pass
    return 0


def extract_condition(name):
    """Extract product condition from name (New, Refurbished, Open Box)."""
    name_lower = name.lower()

    if 'refurbished' in name_lower:
        if '(excellent)' in name_lower or 'excellent' in name_lower:
            return 'Refurbished (Excellent)'
        elif '(good)' in name_lower or 'good' in name_lower:
            return 'Refurbished (Good)'
        elif '(fair)' in name_lower:
            return 'Refurbished (Fair)'
        return 'Refurbished'
    elif 'open box' in name_lower:
        return 'Open Box'
    else:
        return 'New'


def extract_specs(name, category='laptop'):
    """Extract specs from a product name string.

    For 'laptop' or 'desktop': CPU, RAM, storage, GPU, screen, resolution.
    For 'ram': capacity, type (DDR4/DDR5), speed, kit config.
    For 'cpu': model, generation, core count.
    For 'gpu': model, VRAM.
    For other categories: returns basic specs dict.
    """
    if category == 'ram':
        return extract_ram_specs(name)
    elif category == 'cpu':
        return extract_cpu_specs(name)
    elif category == 'gpu':
        return extract_gpu_specs(name)

    # Default: laptop/desktop spec extraction
    specs = {
        'cpu_gen': 0,
        'cpu_model': 'Unknown',
        'ram': 0,
        'storage': 0,
        'gpu': 'Integrated',
        'screen_size': 0,
        'resolution': 'Unknown'
    }

    # Intel Core iX-XXXXX (e.g., i7-13620H, i5-12450H)
    intel_match = re.search(r'(i\d)-(\d{4,5})', name)
    if intel_match:
        specs['cpu_model'] = f"{intel_match.group(1)}-{intel_match.group(2)}"
        model_num = intel_match.group(2)
        if len(model_num) == 5:
            specs['cpu_gen'] = int(model_num[:2])
        elif len(model_num) == 4:
            specs['cpu_gen'] = int(model_num[0])

    # Intel Core Ultra (newer chips, treat as gen 14+)
    ultra_match = re.search(r'(?:Core\s+)?Ultra\s*(\d+)', name, re.IGNORECASE)
    if ultra_match:
        specs['cpu_gen'] = 14
        specs['cpu_model'] = f"Ultra {ultra_match.group(1)}"

    # AMD Ryzen (e.g., Ryzen 7 7840HS)
    amd_match = re.search(r'Ryzen\s*(\d)\s*(\d{4})', name, re.IGNORECASE)
    if amd_match:
        specs['cpu_model'] = f"Ryzen {amd_match.group(1)} {amd_match.group(2)}"
        series = int(amd_match.group(2)[0])
        specs['cpu_gen'] = series + 6

    # Qualcomm Snapdragon X
    if re.search(r'Snapdragon\s*X', name, re.IGNORECASE):
        specs['cpu_gen'] = 14
        snap_match = re.search(r'Snapdragon\s*X\s*(\w+)', name, re.IGNORECASE)
        if snap_match:
            specs['cpu_model'] = f"Snapdragon X {snap_match.group(1)}"

    # RAM - multiple patterns to catch various formats
    ram_patterns = [
        r'(\d+)\s*GB\s*(?:DDR\d?)?\s*RAM',
        r'(\d+)\s*GB\s*DDR\d',
        r'[,/\s](\d+)\s*GB[,/\s]',
        r'(\d+)GB(?:\s|,|/|-|$)',
        r'[^\d](\d+)\s*GB\s+(?:Memory|Mem)',
        r'-\s*(\d+)GB',
    ]
    for pattern in ram_patterns:
        ram_match = re.search(pattern, name, re.IGNORECASE)
        if ram_match:
            ram_val = int(ram_match.group(1))
            if ram_val in [8, 12, 16, 24, 32, 48, 64, 96, 128]:
                specs['ram'] = ram_val
                break

    # Storage - multiple patterns for SSD/storage
    storage_patterns = [
        r'(\d+(?:\.\d+)?)\s*(TB|GB)\s*SSD',
        r'(\d+(?:\.\d+)?)\s*(TB|GB)\s*(?:NVMe|PCIe)',
        r'SSD[:\s]*(\d+(?:\.\d+)?)\s*(TB|GB)',
        r'(\d+(?:\.\d+)?)\s*(TB|GB)\s*(?:Storage|Hard|Drive)',
        r'[,/\s](\d+)\s*(TB)[,/\s]',
        r'[,/\s](512|256|1024|2048)\s*GB[,/\s]',
    ]
    for pattern in storage_patterns:
        storage_match = re.search(pattern, name, re.IGNORECASE)
        if storage_match:
            if len(storage_match.groups()) >= 2:
                specs['storage'] = parse_size(f"{storage_match.group(1)}{storage_match.group(2)}")
            else:
                specs['storage'] = parse_size(f"{storage_match.group(1)}GB")
            break

    # GPU
    gpu_match = re.search(r'(RTX\s*\d{4}(?:\s*Ti)?|GTX\s*\d{4})', name, re.IGNORECASE)
    if gpu_match:
        specs['gpu'] = gpu_match.group(1).upper().replace("  ", " ")

    # AMD GPU
    amd_gpu_match = re.search(r'(RX\s*\d{4}(?:\s*XT)?)', name, re.IGNORECASE)
    if amd_gpu_match and specs['gpu'] == 'Integrated':
        specs['gpu'] = amd_gpu_match.group(1).upper().replace("  ", " ")

    # Screen size (e.g., 15.6", 14", 17.3")
    screen_patterns = [
        r'(\d{1,2}(?:\.\d)?)["\u201d\u2033]\s*(?:FHD|QHD|UHD|HD|OLED|IPS|LED)?',
        r'(\d{1,2}(?:\.\d)?)\s*(?:inch|in)\b',
        r'(\d{1,2}(?:\.\d)?)\s*(?:FHD|QHD|UHD|HD|OLED)',
    ]
    for pattern in screen_patterns:
        screen_match = re.search(pattern, name, re.IGNORECASE)
        if screen_match:
            size = float(screen_match.group(1))
            if 10 <= size <= 40:  # Valid screen sizes (up to 40 for desktops/monitors)
                specs['screen_size'] = size
                break

    # Resolution (FHD, QHD, UHD/4K, HD, etc.)
    resolution_map = {
        r'\b4K\b': '4K UHD',
        r'\bUHD\b': '4K UHD',
        r'\bQHD\+': 'QHD+',
        r'\bQHD\b': 'QHD',
        r'\bWQXGA\b': 'WQXGA',
        r'\bFHD\+': 'FHD+',
        r'\bFHD\b': 'FHD',
        r'\b1080p\b': 'FHD',
        r'\b1440p\b': 'QHD',
        r'\b2160p\b': '4K UHD',
        r'\bHD\+': 'HD+',
        r'\bHD\b': 'HD',
        r'\bOLED\b': 'OLED',
    }
    for pattern, resolution in resolution_map.items():
        if re.search(pattern, name, re.IGNORECASE):
            if resolution == 'OLED':
                specs['resolution'] = 'OLED'
                continue
            specs['resolution'] = resolution
            break

    return specs


RAM_BRANDS = [
    'corsair', 'g.skill', 'gskill', 'kingston', 'crucial', 'teamgroup',
    'team', 'patriot', 'pny', 'samsung', 'sk hynix', 'hynix', 'micron',
    'adata', 'mushkin', 'oloy', 'v-color', 'silicon power',
    'thermaltake', 'hp', 'lexar',
]


def extract_ram_specs(name):
    """Parse RAM stick specs from a product name.

    Examples:
    - "Corsair Vengeance 32GB (2x16GB) DDR5-6000 CL30"
    - "G.Skill Ripjaws V 16GB (2x8GB) DDR4-3200 CL16"
    - "Crucial 32GB DDR4-3200 SODIMM CT32G4SFD832A"
    """
    specs = {
        'ram': 0,
        'ram_type': 'Unknown',
        'ram_speed_mhz': 0,
        'kit_config': '',
        'stick_count': 0,
        'per_stick_gb': 0,
        'cas_latency': 0,
        'form_factor': 'Unknown',
        'brand': '',
        'voltage': 0,
    }

    # Kit configuration first (2x16GB, 4x8GB, etc.) — this gives us the most accurate total
    kit_match = re.search(r'(\d+)\s*x\s*(\d+)\s*GB', name, re.IGNORECASE)
    if kit_match:
        stick_count = int(kit_match.group(1))
        per_stick = int(kit_match.group(2))
        specs['kit_config'] = f"{stick_count}x{per_stick}GB"
        specs['stick_count'] = stick_count
        specs['per_stick_gb'] = per_stick
        specs['ram'] = stick_count * per_stick  # Total capacity from kit
    else:
        # No kit config — look for total capacity
        cap_match = re.search(r'(\d+)\s*GB', name, re.IGNORECASE)
        if cap_match:
            specs['ram'] = int(cap_match.group(1))
            specs['stick_count'] = 1
            specs['per_stick_gb'] = specs['ram']

    # DDR type and speed
    ddr_match = re.search(r'(DDR[45])\s*[-:]?\s*(\d{4,5})', name, re.IGNORECASE)
    if ddr_match:
        specs['ram_type'] = ddr_match.group(1).upper()
        specs['ram_speed_mhz'] = int(ddr_match.group(2))
    else:
        ddr_type_match = re.search(r'(DDR[45])', name, re.IGNORECASE)
        if ddr_type_match:
            specs['ram_type'] = ddr_type_match.group(1).upper()

    # CAS latency
    cl_match = re.search(r'CL(\d+)', name, re.IGNORECASE)
    if cl_match:
        specs['cas_latency'] = int(cl_match.group(1))

    # Form factor: SO-DIMM (laptop) vs DIMM (desktop)
    name_lower = name.lower()
    if any(kw in name_lower for kw in ['sodimm', 'so-dimm', 'soram', 'laptop memory', 'laptop ram', 'notebook']):
        specs['form_factor'] = 'SO-DIMM'
    elif any(kw in name_lower for kw in ['udimm', 'u-dimm', 'desktop memory', 'desktop ram']):
        specs['form_factor'] = 'DIMM'
    elif 'dimm' in name_lower and 'so' not in name_lower.split('dimm')[0][-3:]:
        # "DIMM" without "SO" prefix nearby
        specs['form_factor'] = 'DIMM'

    # Brand
    for brand in RAM_BRANDS:
        if brand in name_lower:
            # Normalize display name
            brand_map = {
                'gskill': 'G.Skill', 'g.skill': 'G.Skill',
                'sk hynix': 'SK Hynix', 'hynix': 'SK Hynix',
                'teamgroup': 'TeamGroup', 'team': 'TeamGroup',
                'silicon power': 'Silicon Power', 'pny': 'PNY',
                'adata': 'ADATA', 'hp': 'HP', 'oloy': 'OLOy',
                'v-color': 'V-Color',
            }
            specs['brand'] = brand_map.get(brand, brand.title())
            break

    # Voltage (e.g., 1.35V, 1.25V, 1.1V)
    volt_match = re.search(r'(\d+\.\d+)\s*V\b', name, re.IGNORECASE)
    if volt_match:
        v = float(volt_match.group(1))
        if 0.9 <= v <= 1.6:  # Valid RAM voltage range
            specs['voltage'] = v

    return specs


def extract_cpu_specs(name):
    """Parse CPU specs from a product name.

    Examples:
    - "AMD Ryzen 7 7800X3D 8-Core 4.2GHz AM5"
    - "Intel Core i7-14700K 20-Core LGA 1700"
    """
    specs = {
        'cpu_model': 'Unknown',
        'cpu_gen': 0,
        'core_count': 0,
        'base_clock_ghz': 0,
        'socket': '',
    }

    # Intel
    intel_match = re.search(r'(i\d)-(\d{4,5}[A-Z]*)', name)
    if intel_match:
        specs['cpu_model'] = f"{intel_match.group(1)}-{intel_match.group(2)}"
        model_num = re.search(r'\d+', intel_match.group(2)).group()
        if len(model_num) == 5:
            specs['cpu_gen'] = int(model_num[:2])
        elif len(model_num) == 4:
            specs['cpu_gen'] = int(model_num[0])

    # Intel Core Ultra
    ultra_match = re.search(r'(?:Core\s+)?Ultra\s*(\d+)\s*(\w*)', name, re.IGNORECASE)
    if ultra_match:
        specs['cpu_gen'] = 14
        specs['cpu_model'] = f"Ultra {ultra_match.group(1)}"

    # AMD Ryzen
    amd_match = re.search(r'Ryzen\s*(\d)\s*(\d{4}\w*)', name, re.IGNORECASE)
    if amd_match:
        specs['cpu_model'] = f"Ryzen {amd_match.group(1)} {amd_match.group(2)}"
        series = int(amd_match.group(2)[0])
        specs['cpu_gen'] = series + 6

    # Core count
    core_match = re.search(r'(\d+)\s*-?\s*[Cc]ore', name)
    if core_match:
        specs['core_count'] = int(core_match.group(1))

    # Base clock
    clock_match = re.search(r'(\d+(?:\.\d+)?)\s*GHz', name, re.IGNORECASE)
    if clock_match:
        specs['base_clock_ghz'] = float(clock_match.group(1))

    # Socket
    socket_patterns = [
        r'(AM[45])',
        r'(LGA\s*\d{4})',
        r'(Socket\s*\w+)',
    ]
    for pattern in socket_patterns:
        socket_match = re.search(pattern, name, re.IGNORECASE)
        if socket_match:
            specs['socket'] = socket_match.group(1).strip()
            break

    return specs


def extract_gpu_specs(name):
    """Parse GPU/graphics card specs from a product name.

    Examples:
    - "ASUS TUF Gaming GeForce RTX 4070 Ti SUPER 16GB OC"
    - "MSI Gaming X Trio Radeon RX 7900 XTX 24GB"
    """
    specs = {
        'gpu': 'Unknown',
        'vram_gb': 0,
    }

    # NVIDIA
    nvidia_match = re.search(r'((?:GeForce\s+)?(?:RTX|GTX)\s*\d{4}(?:\s*Ti)?(?:\s*(?:SUPER|Super))?)', name, re.IGNORECASE)
    if nvidia_match:
        specs['gpu'] = nvidia_match.group(1).strip()

    # AMD
    amd_match = re.search(r'((?:Radeon\s+)?RX\s*\d{4}(?:\s*(?:XT|XTX))?)', name, re.IGNORECASE)
    if amd_match and specs['gpu'] == 'Unknown':
        specs['gpu'] = amd_match.group(1).strip()

    # Intel Arc
    arc_match = re.search(r'(Arc\s*A\d{3}\w?)', name, re.IGNORECASE)
    if arc_match and specs['gpu'] == 'Unknown':
        specs['gpu'] = arc_match.group(1).strip()

    # VRAM
    vram_match = re.search(r'(\d+)\s*GB(?:\s*(?:GDDR|VRAM))?', name, re.IGNORECASE)
    if vram_match:
        vram = int(vram_match.group(1))
        if vram in [2, 3, 4, 6, 8, 10, 12, 16, 24, 48]:
            specs['vram_gb'] = vram

    return specs


RESOLUTION_RANK = {
    "HD": 1, "HD+": 2, "FHD": 3, "FHD+": 4,
    "QHD": 5, "WQXGA": 5, "QHD+": 6, "4K UHD": 7,
    "OLED": 4, "Unknown": 0
}


# Keywords used to auto-detect product category from name
_CATEGORY_KEYWORDS = {
    'laptop': ['laptop', 'notebook', 'chromebook', 'macbook', 'thinkpad', 'ideapad',
               'pavilion', 'inspiron', 'vivobook', 'zenbook', 'swift', 'nitro',
               'predator', 'legion', 'rog strix', 'tuf gaming'],
    'desktop': ['desktop', 'tower', 'all-in-one', 'mini pc', 'nuc', 'imac',
                'optiplex', 'thinkcentre', 'prodesk'],
    'ram': ['ddr4', 'ddr5', 'sodimm', 'dimm', 'memory module', 'ram kit',
            'vengeance', 'ripjaws', 'trident z', 'fury beast', 'ballistix'],
    'cpu': ['processor', 'ryzen 5 ', 'ryzen 7 ', 'ryzen 9 ', 'core i5-', 'core i7-',
            'core i9-', 'core ultra', 'threadripper'],
    'gpu': ['graphics card', 'video card', 'geforce rtx', 'geforce gtx',
            'radeon rx', 'arc a'],
    'motherboard': ['motherboard', 'mainboard', 'mobo'],
    'psu': ['power supply', 'psu', 'watt'],
    'cooler': ['cpu cooler', 'aio', 'liquid cooler', 'air cooler', 'heatsink'],
    'case': ['computer case', 'pc case', 'atx case', 'tower case', 'mid-tower',
             'full-tower', 'mini-itx'],
    'ssd': ['ssd', 'nvme', 'solid state', 'm.2'],
}


def categorize_product(name):
    """Auto-detect product category from name keywords.

    Returns one of: 'laptop', 'desktop', 'ram', 'cpu', 'gpu', 'motherboard',
    'psu', 'cooler', 'case', 'ssd', 'other'
    """
    name_lower = name.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return category
    return 'other'
