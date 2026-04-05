"""
System spec detection for Windows.

Reads current PC specs using Windows system commands.
Works on the local machine where the app is running.
"""

import subprocess
import re
import json


def detect_specs():
    """Detect current system specs on Windows.

    Returns dict with: cpu_name, cpu_gen, ram_gb, storage_gb, gpu, screen info.
    """
    specs = {
        'cpu_name': '',
        'cpu_gen': 0,
        'ram_gb': 0,
        'ram_type': '',
        'ram_speed_mhz': 0,
        'ram_sticks': 0,
        'storage': [],  # list of {size_gb, type, model}
        'gpu': '',
        'os': '',
        'screen_resolution': '',
    }

    # CPU
    try:
        result = _run_cmd('wmic cpu get name /value')
        match = re.search(r'Name=(.+)', result)
        if match:
            cpu_name = match.group(1).strip()
            specs['cpu_name'] = cpu_name
            specs['cpu_gen'] = _parse_cpu_gen(cpu_name)
    except Exception:
        pass

    # RAM - total
    try:
        result = _run_cmd('wmic computersystem get totalphysicalmemory /value')
        match = re.search(r'TotalPhysicalMemory=(\d+)', result)
        if match:
            specs['ram_gb'] = round(int(match.group(1)) / (1024 ** 3))
    except Exception:
        pass

    # RAM - details (type, speed, stick count)
    try:
        result = _run_cmd('wmic memorychip get capacity,speed,memorytype,smbiosmemorytype /format:list')
        sticks = result.strip().split('\n\n')
        stick_count = 0
        speeds = []
        for stick in sticks:
            if 'Capacity=' in stick:
                stick_count += 1
            speed_match = re.search(r'Speed=(\d+)', stick)
            if speed_match:
                s = int(speed_match.group(1))
                if s > 0:
                    speeds.append(s)
            # SMBIOSMemoryType: 26=DDR4, 34=DDR5
            type_match = re.search(r'SMBIOSMemoryType=(\d+)', stick)
            if type_match:
                smbios = int(type_match.group(1))
                if smbios == 26:
                    specs['ram_type'] = 'DDR4'
                elif smbios == 34:
                    specs['ram_type'] = 'DDR5'
                elif smbios == 24:
                    specs['ram_type'] = 'DDR3'
        specs['ram_sticks'] = stick_count
        if speeds:
            specs['ram_speed_mhz'] = max(speeds)
    except Exception:
        pass

    # Storage
    try:
        result = _run_cmd('wmic diskdrive get model,size,mediatype /format:list')
        entries = result.strip().split('\n\n')
        for entry in entries:
            model_match = re.search(r'Model=(.+)', entry)
            size_match = re.search(r'Size=(\d+)', entry)
            media_match = re.search(r'MediaType=(.+)', entry)
            if size_match:
                size_gb = round(int(size_match.group(1)) / (1024 ** 3))
                model = model_match.group(1).strip() if model_match else 'Unknown'
                media = media_match.group(1).strip() if media_match else ''
                model_lower = model.lower()
                drive_type = 'SSD' if any(x in model_lower for x in ['ssd', 'nvme', 'solid', 'pcie', 'samsung 9', 'samsung 8', 'wd_black', 'sabrent', 'crucial', 'kingston']) else 'HDD'
                # Most modern drives under 2TB are SSDs
                if drive_type == 'HDD' and size_gb < 2048 and 'fixed' in media.lower():
                    drive_type = 'SSD (likely)'
                if size_gb > 10:  # Skip tiny system partitions
                    specs['storage'].append({
                        'size_gb': size_gb,
                        'type': drive_type,
                        'model': model,
                    })
    except Exception:
        pass

    # GPU — use safe registry query instead of wmic video controller
    # (wmic videocontroller can disrupt external displays on some systems)
    try:
        result = _run_cmd('reg query "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}" /s /v DriverDesc 2>nul')
        gpus = re.findall(r'DriverDesc\s+REG_SZ\s+(.+)', result)
        dedicated = [g.strip() for g in gpus if not any(x in g.lower() for x in ['basic', 'microsoft', 'parsec', 'virtual'])]
        if dedicated:
            specs['gpu'] = dedicated[0]
        elif gpus:
            specs['gpu'] = gpus[0].strip()
    except Exception:
        pass

    # OS
    try:
        result = _run_cmd('wmic os get caption /value')
        match = re.search(r'Caption=(.+)', result)
        if match:
            specs['os'] = match.group(1).strip()
    except Exception:
        pass

    return specs


def _run_cmd(cmd):
    """Run a Windows command and return output."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
    )
    return result.stdout


def _parse_cpu_gen(cpu_name):
    """Parse CPU generation from name string."""
    # Intel Core iX-XXXXX
    intel_match = re.search(r'i\d-(\d{4,5})', cpu_name)
    if intel_match:
        model = intel_match.group(1)
        if len(model) == 5:
            return int(model[:2])
        elif len(model) == 4:
            return int(model[0])

    # Intel Core Ultra
    if 'Ultra' in cpu_name:
        return 14

    # AMD Ryzen
    amd_match = re.search(r'Ryzen\s*\d\s*(\d)\d{3}', cpu_name)
    if amd_match:
        return int(amd_match.group(1)) + 6

    return 0


def format_specs_summary(specs):
    """Format detected specs as a readable summary."""
    lines = []

    if specs.get('cpu_name'):
        gen_str = f" (Gen {specs['cpu_gen']})" if specs['cpu_gen'] > 0 else ""
        lines.append(f"**CPU:** {specs['cpu_name']}{gen_str}")

    if specs.get('ram_gb'):
        ram_str = f"**RAM:** {specs['ram_gb']}GB"
        details = []
        if specs.get('ram_type'):
            details.append(specs['ram_type'])
        if specs.get('ram_speed_mhz'):
            details.append(f"{specs['ram_speed_mhz']}MHz")
        if specs.get('ram_sticks'):
            details.append(f"{specs['ram_sticks']} stick(s)")
        if details:
            ram_str += f" ({', '.join(details)})"
        lines.append(ram_str)

    if specs.get('storage'):
        for i, drive in enumerate(specs['storage']):
            size_str = f"{drive['size_gb']}GB" if drive['size_gb'] < 1000 else f"{drive['size_gb'] / 1024:.1f}TB"
            lines.append(f"**Storage {i+1}:** {size_str} {drive['type']} — {drive['model']}")

    if specs.get('gpu'):
        lines.append(f"**GPU:** {specs['gpu']}")

    if specs.get('screen_resolution'):
        res_name = specs.get('screen_resolution_name', '')
        lines.append(f"**Display:** {specs['screen_resolution']}" + (f" ({res_name})" if res_name else ""))

    if specs.get('os'):
        lines.append(f"**OS:** {specs['os']}")

    return "\n\n".join(lines)


# ── Upgrade Recommendations ──

USAGE_PROFILES = {
    'office': {
        'name': 'Office / Web Browsing',
        'description': 'Email, documents, spreadsheets, web browsing',
        'recommended': {'ram': 16, 'storage': 256, 'cpu_gen': 11, 'gpu': 'Integrated', 'resolution': 'FHD'},
    },
    'gaming': {
        'name': 'Gaming',
        'description': 'Modern games at decent settings',
        'recommended': {'ram': 32, 'storage': 1024, 'cpu_gen': 13, 'gpu': 'RTX 4060', 'resolution': 'FHD'},
    },
    'creative': {
        'name': 'Creative / Video Editing',
        'description': 'Photoshop, Premiere Pro, DaVinci Resolve',
        'recommended': {'ram': 64, 'storage': 2048, 'cpu_gen': 13, 'gpu': 'RTX 4070', 'resolution': 'QHD'},
    },
    'programming': {
        'name': 'Software Development',
        'description': 'IDEs, Docker, VMs, compiling',
        'recommended': {'ram': 32, 'storage': 1024, 'cpu_gen': 12, 'gpu': 'Integrated', 'resolution': 'FHD'},
    },
    'student': {
        'name': 'Student / Light Use',
        'description': 'Notes, research, light multitasking',
        'recommended': {'ram': 16, 'storage': 256, 'cpu_gen': 10, 'gpu': 'Integrated', 'resolution': 'FHD'},
    },
    'ai_ml': {
        'name': 'AI / Machine Learning',
        'description': 'Model training, data science, large datasets',
        'recommended': {'ram': 64, 'storage': 2048, 'cpu_gen': 13, 'gpu': 'RTX 4080', 'resolution': 'FHD'},
    },
}


def get_upgrade_recommendations(current_specs, usage_profile):
    """Compare current specs against recommended for a usage profile.

    Returns list of recommendation dicts with priority.
    """
    profile = USAGE_PROFILES.get(usage_profile)
    if not profile:
        return []

    rec = profile['recommended']
    recommendations = []

    # RAM
    current_ram = current_specs.get('ram_gb', 0)
    rec_ram = rec.get('ram', 16)
    if current_ram < rec_ram:
        urgency = 'high' if current_ram < rec_ram // 2 else 'medium'
        recommendations.append({
            'component': 'RAM',
            'current': f"{current_ram}GB",
            'recommended': f"{rec_ram}GB",
            'urgency': urgency,
            'reason': f"For {profile['name'].lower()}, {rec_ram}GB is recommended. You have {current_ram}GB.",
            'search_hint': f"{rec_ram}GB {current_specs.get('ram_type', 'DDR4')} RAM",
        })

    # Storage
    total_storage = sum(d.get('size_gb', 0) for d in current_specs.get('storage', []))
    rec_storage = rec.get('storage', 512)
    if total_storage < rec_storage:
        urgency = 'high' if total_storage < rec_storage // 2 else 'medium'
        rec_str = f"{rec_storage}GB" if rec_storage < 1024 else f"{rec_storage // 1024}TB"
        cur_str = f"{total_storage}GB" if total_storage < 1024 else f"{total_storage / 1024:.1f}TB"
        recommendations.append({
            'component': 'Storage',
            'current': cur_str,
            'recommended': rec_str,
            'urgency': urgency,
            'reason': f"For {profile['name'].lower()}, {rec_str} is recommended. You have {cur_str}.",
            'search_hint': f"1TB NVMe SSD",
        })

    # CPU
    current_gen = current_specs.get('cpu_gen', 0)
    rec_gen = rec.get('cpu_gen', 11)
    if current_gen > 0 and current_gen < rec_gen:
        urgency = 'high' if current_gen < rec_gen - 3 else 'medium'
        recommendations.append({
            'component': 'CPU / System',
            'current': f"Gen {current_gen}",
            'recommended': f"Gen {rec_gen}+",
            'urgency': urgency,
            'reason': f"Your CPU (Gen {current_gen}) is behind the recommended Gen {rec_gen}+. This usually means upgrading the whole laptop/desktop.",
            'search_hint': f"laptop i7 Gen {rec_gen}",
        })

    # GPU
    current_gpu = current_specs.get('gpu', 'Integrated')
    rec_gpu = rec.get('gpu', 'Integrated')
    if rec_gpu != 'Integrated':
        is_integrated = any(x in current_gpu.lower() for x in ['intel', 'uhd', 'iris', 'integrated', 'radeon graphics'])
        if is_integrated:
            recommendations.append({
                'component': 'GPU',
                'current': current_gpu,
                'recommended': f"{rec_gpu} or better",
                'urgency': 'high',
                'reason': f"For {profile['name'].lower()}, a dedicated GPU like {rec_gpu} is strongly recommended. You have integrated graphics.",
                'search_hint': f"laptop {rec_gpu}",
            })

    if not recommendations:
        recommendations.append({
            'component': 'All Good!',
            'current': '',
            'recommended': '',
            'urgency': 'none',
            'reason': f"Your system meets the recommended specs for {profile['name'].lower()}. No upgrades needed!",
            'search_hint': '',
        })

    return recommendations
