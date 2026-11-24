"""Prepare the known laboratory devices and supervise only processes we own."""

import argparse
import csv
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / '.lab-run'
STATE = STATE_DIR / 'state.json'
LAYOUT = ROOT / 'src/godirect_ros2/config/plotjuggler_four_shimmers_config.xml'
DATA_DIR = ROOT / 'grip_data'
FORCE_TOPIC = '/grip_force_stream'
ESTIMATED_FORCE_TOPIC = '/grip_force_estimated'
RECORDING_ID = re.compile(r'[0-9a-f]{32}')
DEFAULT_SHIMMER = 2
AUTO_SHIMMER_ORDER = (2, 4, 1, 3)
DEVICES = (
    (0, '00:06:66:B1:4C:91', 1, 'Shimmer_4C91'),
    (1, '60:8A:10:40:9D:2C', 6, 'Shimmer_9D2C'),
    (2, '00:06:66:B1:4C:87', 1, 'Shimmer_4C87'),
    (3, '60:8A:10:40:9D:23', 6, 'Shimmer_9D23'),
)


def say(message):
    print(message, flush=True)


def run(command, timeout=12, check=True):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'{" ".join(command)}: {result.stdout.strip()}')
    return result.stdout


def process_identity(pid):
    """Use start ticks as well as PID; never signal a recycled PID."""
    try:
        proc = Path(f'/proc/{pid}')
        if proc.stat().st_uid != os.getuid():
            return None
        fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError):
        return None


def is_same_process(record):
    return bool(record and record.get('start') and
                process_identity(record['pid']) == record['start'])


def read_state():
    try:
        return json.loads(STATE.read_text())
    except FileNotFoundError:
        return {}


def save_state(state):
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(STATE)


def stop_owned(records):
    # All children are started in a new session, with pgid == pid.
    for sig, seconds in [(signal.SIGINT, 8), (signal.SIGTERM, 3), (signal.SIGKILL, 1)]:
        live = [r for r in records if is_same_process(r)]
        if not live:
            break
        for record in live:
            try:
                if os.getpgid(record['pid']) == record['pid']:
                    os.killpg(record['pid'], sig)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and any(is_same_process(r) for r in live):
            time.sleep(0.1)


def stop():
    state = read_state()
    supervisor = state.get('supervisor')
    if is_same_process(supervisor):
        os.kill(supervisor['pid'], signal.SIGINT)
        deadline = time.monotonic() + 15
        while is_same_process(supervisor) and time.monotonic() < deadline:
            time.sleep(0.1)
        if is_same_process(supervisor):
            raise RuntimeError('Pokretač se još zaustavlja; provjerite njegov terminal.')
    else:
        stop_owned(state.get('children', []))
        STATE.unlink(missing_ok=True)
    say('Zaustavljeni su procesi ovog pokretača. Ranije zasebno pokrenuti čvorovi ostaju netaknuti.')


def binding_matches(description, mac, channel):
    return bool(re.search(rf'{re.escape(mac)}\s+channel\s+{channel}\b',
                          description, re.IGNORECASE))


def needs_binding(port, mac, channel):
    description = run(['rfcomm', 'show', str(port)], check=False)
    if binding_matches(description, mac, channel):
        return False
    if re.search(r'\bconnected\b|\bconnecting\b|\bdisconnecting\b|tty-attached', description):
        raise RuntimeError(f'rfcomm{port} zauzet je drugom vezom; neću ga prevezati: {description.strip()}')
    return True


def pair_device(mac):
    try:
        import pexpect
    except ImportError as error:
        raise RuntimeError(f'Za prvo uparivanje nedostaje python3-pexpect. '
                           f'Uparite {mac} kroz bluetoothctl, PIN 1234.') from error
    say(f'Uparujem {mac} sa standardnim Shimmer PIN-om 1234…')
    child = pexpect.spawn('bluetoothctl', encoding='utf-8', timeout=30)
    try:
        child.expect('Agent registered')
        child.sendline('default-agent')
        child.expect('Default agent request successful')
        child.sendline('scan on')
        child.expect(['Discovery started', 'InProgress'])
        # Wait until the target is known, rather than pairing the first nearby device.
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            info = run(['bluetoothctl', 'info', mac], check=False)
            if 'Name:' in info and 'not available' not in info:
                break
            time.sleep(0.5)
        child.sendline('pair ' + mac)
        result = child.expect(['Enter PIN code:', 'Pairing successful',
                               'AlreadyExists', 'Failed to pair:', 'not available'])
        if result == 0:
            child.sendline('1234')
            result = child.expect(['Pairing successful', 'Failed to pair:'])
            if result != 0:
                raise RuntimeError(f'Uparivanje nije uspjelo za {mac}; provjerite je li uređaj uključen.')
        elif result not in (1, 2):
            raise RuntimeError(f'Uparivanje nije uspjelo za {mac}; provjerite je li uređaj uključen.')
    except pexpect.TIMEOUT as error:
        raise RuntimeError(f'Isteklo je čekanje uparivanja {mac}. Provjerite napajanje i blizinu.') from error
    finally:
        child.sendline('scan off')
        # Await confirmation so discovery is not left running after closing the agent.
        try:
            child.expect(['Discovering: no', 'NotReady'], timeout=5)
        except (pexpect.TIMEOUT, pexpect.EOF):
            pass
        child.sendline('quit')
        child.close()


def prepare(devices):
    for command in ['bluetoothctl', 'rfcomm', 'sudo', 'ros2', 'fuser']:
        if not shutil.which(command):
            raise RuntimeError(f'Nedostaje naredba {command}.')
    controller = run(['bluetoothctl', 'show'], check=False)
    if 'Controller ' not in controller:
        raise RuntimeError('Bluetooth adapter nije dostupan.')
    if 'Powered: yes' not in controller:
        run(['bluetoothctl', 'power', 'on'])
    for _, mac, _, _ in devices:
        info = run(['bluetoothctl', 'info', mac], check=False)
        if 'Blocked: yes' in info:
            raise RuntimeError(f'{mac} je blokiran u Bluetooth postavkama.')
        if 'Paired: yes' not in info:
            pair_device(mac)
        if 'Trusted: yes' not in info:
            run(['bluetoothctl', 'trust', mac])

    changes = [(p, m, c) for p, m, c, _ in devices if needs_binding(p, m, c)]
    if changes:
        say('Potrebna je priprema RFCOMM portova. Sudo lozinku unesite samo u terminal.')
        if os.geteuid() != 0:
            subprocess.run(['sudo', '-v'], check=True)
        prefix = [] if os.geteuid() == 0 else ['sudo']
        for port, mac, channel in changes:
            # Recheck immediately before changing a binding.
            if not needs_binding(port, mac, channel):
                continue
            run(prefix + ['rfcomm', 'release', str(port)], check=False)
            run(prefix + ['rfcomm', 'bind', str(port), mac, str(channel)])
            if needs_binding(port, mac, channel):
                raise RuntimeError(f'Nije uspjelo vezanje rfcomm{port}.')
    for port, _, _, _ in devices:
        path = f'/dev/rfcomm{port}'
        if not os.access(path, os.R_OK | os.W_OK):
            raise RuntimeError(f'Nema prava pristupa {path}. Izvršite sudo usermod -aG dialout "$USER", '
                               'zatim se odjavite i ponovno prijavite.')
    say(f'Bluetooth i RFCOMM portovi spremni su za {len(devices)} Shimmera.')


class Monitor:
    def __init__(self, devices, estimation_only=False):
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
        from emg_grip_interfaces.msg import Emg, GripForce
        self.ros = rclpy
        rclpy.init(args=[])
        self.node = Node(f'lab_pokretac_{os.getpid()}')
        self.topics = ({ESTIMATED_FORCE_TOPIC: 'grip_estimated'} if estimation_only
                       else {FORCE_TOPIC: 'grip'})
        for port, _, _, name in devices:
            for stream in ('emg_stream', 'emg_processed'):
                self.topics[f'/shimmer{port + 1}/{stream}'] = name
        self.samples = {topic: [0, 0.0, ''] for topic in self.topics}
        self.subscriptions = {}
        for topic in self.topics:
            kind = GripForce if topic in (FORCE_TOPIC, ESTIMATED_FORCE_TOPIC) else Emg
            self.subscriptions[topic] = self.node.create_subscription(
                kind, topic, lambda msg, key=topic: self.receive(key, msg), qos_profile_sensor_data)

    def unwatch_shimmer(self, index):
        for stream in ('emg_stream', 'emg_processed'):
            topic = f'/shimmer{index}/{stream}'
            self.node.destroy_subscription(self.subscriptions.pop(topic))
            del self.topics[topic]
            del self.samples[topic]

    def receive(self, topic, msg):
        record = self.samples[topic]
        record[0] += 1
        record[1] = time.monotonic()
        record[2] = msg.header.frame_id

    def spin(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.ros.spin_once(self.node, timeout_sec=0.05)

    def ready(self, topic):
        count, last, name = self.samples[topic]
        if count and name != self.topics[topic]:
            raise RuntimeError(f'{topic} ima frame_id={name}, očekivano {self.topics[topic]}.')
        return count >= 3 and time.monotonic() - last < 2

    def close(self):
        self.node.destroy_node()
        if self.ros.ok():
            self.ros.shutdown()


def make_layout(path, shimmers, estimation_only=False):
    tree = ET.parse(LAYOUT)
    tab = tree.find('./tabbed_widget/Tab')
    tab.set('tab_name', 'EMG i sila stiska')
    splitter = tab.find('./Container/DockSplitter')
    topics = []
    for index, panel in enumerate(splitter.findall('DockArea')[:-1], 1):
        if index not in shimmers:
            splitter.remove(panel)
            continue
        topics.append(f'/shimmer{index}/emg_processed')
        panel.set('name', panel.get('name').replace('EMG', 'obrađeni EMG'))
        for curve in panel.findall('./plot/curve'):
            curve.set('name', curve.get('name').replace('emg_stream', 'emg_processed'))
    plot = splitter.find('DockArea[last()]/plot')
    if estimation_only:
        for curve in plot.findall('curve'):
            plot.remove(curve)
    else:
        topics.extend((FORCE_TOPIC, '/grip_force_target'))
        ET.SubElement(plot, 'curve', name='/grip_force_target/grip_force', color='#9467bd')
    topics.append(ESTIMATED_FORCE_TOPIC)
    ET.SubElement(plot, 'curve', name=f'{ESTIMATED_FORCE_TOPIC}/grip_force', color='#e6550d')
    splitter.set('count', str(len(splitter)))
    splitter.set('sizes', ';'.join(['1'] * len(splitter)))
    plugin = tree.find("./Plugins/plugin[@ID='ROS2 Topic Subscriber']/selected_topics")
    plugin.set('value', ';'.join(topics))
    tree.write(path, encoding='utf-8', xml_declaration=True)


def start(no_gui, shimmers, data_dir, emg_hz, model_path=None):
    estimation_only = model_path is not None
    devices = [DEVICES[index - 1] for index in (shimmers or AUTO_SHIMMER_ORDER)]
    lock = (STATE_DIR / 'launcher.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        say('Pokretač je već aktivan. Provjera: ./pokreni.sh status; završetak: ./pokreni.sh stop')
        return 0
    state = read_state()
    state = {'supervisor': {'pid': os.getpid(), 'start': process_identity(os.getpid())},
             'shimmers': shimmers, 'data_dir': str(data_dir), 'estimation_only': estimation_only,
             'children': [r for r in state.get('children', []) if is_same_process(r)]}
    logs = STATE_DIR / time.strftime('%Y%m%d-%H%M%S')
    logs.mkdir(exist_ok=True)
    save_state(state)
    monitor = None
    children = []

    def spawn(name, command):
        path = logs / f'{name}.log'
        with path.open('a') as output:
            process = subprocess.Popen(command, cwd=ROOT, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        record = {'pid': process.pid, 'start': process_identity(process.pid),
                  'name': name, 'log': str(path)}
        children.append(process)
        state['children'].append(record)
        save_state(state)
        say(f'Pokrećem {name}; zapis: {path}')
        return process, path

    def publisher_rate(topic):
        from rcl_interfaces.srv import GetParameters

        publishers = monitor.node.get_publishers_info_by_topic(topic)
        if len(publishers) != 1:
            raise RuntimeError(f'{topic} mora imati točno jednog publishera.')
        publisher = publishers[0]
        namespace = publisher.node_namespace.rstrip('/')
        client = monitor.node.create_client(
            GetParameters, f'{namespace}/{publisher.node_name}/get_parameters')
        try:
            if client.wait_for_service(timeout_sec=3):
                future = client.call_async(GetParameters.Request(names=['sampling_rate']))
                monitor.ros.spin_until_future_complete(monitor.node, future, timeout_sec=3)
                values = future.result().values if future.done() else []
                if values and math.isfinite(values[0].double_value) and values[0].double_value > 0:
                    return values[0].double_value
            raise RuntimeError(f'Ne mogu provjeriti sampling_rate za {topic}.')
        finally:
            monitor.node.destroy_client(client)

    def ensure_stream(topic, name, command, port=None):
        publishers = monitor.node.count_publishers(topic)
        if not publishers and port is not None:
            busy = subprocess.run(['fuser', f'/dev/rfcomm{port}'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if busy.returncode == 0:
                deadline = time.monotonic() + 10
                while not publishers and time.monotonic() < deadline:
                    monitor.spin(0.1)
                    publishers = monitor.node.count_publishers(topic)
                if not publishers:
                    raise RuntimeError(f'rfcomm{port} je zauzet, a {topic} nije vidljiv. '
                                       'Provjerite ROS_DOMAIN_ID i postojeće čvorove.')
        if publishers > 1:
            raise RuntimeError(f'{topic} ima više publishera; uklonite duplikate prije pokretanja.')
        process, log = None, None
        if publishers:
            say(f'Provjeravam postojeći {name}…')
            if port is not None:
                current = publisher_rate(topic)
                if not math.isclose(current, emg_hz, abs_tol=0.01):
                    raise RuntimeError(f'{topic} koristi {current:g} Hz, zadano je {emg_hz:g} Hz. '
                                       'Zaustavite postojeći čvor ili zadajte njegov --emg-hz.')
        else:
            process, log = spawn(name, command)
        timeout = 40
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            monitor.spin(0.1)
            if monitor.ready(topic):
                say(f'OK {name}: primljeni novi uzorci na {topic}')
                return
            if process is not None and process.poll() is not None:
                tail = '\n'.join(log.read_text(errors='replace').splitlines()[-8:])
                raise RuntimeError(f'{name} se ugasio.\n{tail}')
        detail = str(log) if log else 'postojeći proces nije pokrenuo ovaj pokretač'
        raise RuntimeError(f'{name}: nema svježih podataka unutar {timeout} s. Zapis: {detail}')

    def start_shimmer(port):
        name = f'shimmer{port + 1}'
        ensure_stream(f'/{name}/emg_stream', name,
                      ['ros2', 'run', 'shimmer_ros2', 'shimmer_publisher', '--ros-args',
                       '-r', f'__ns:=/{name}', '-r', '__node:=emg_publisher',
                       '-p', f'rfcomm_port_num:={port}', '-p', f'sampling_rate:={emg_hz}',
                       '-p', 'queue_size:=2048'], port)

    def select_shimmer():
        candidates = sorted(devices, key=lambda device: not monitor.node.count_publishers(
            f'/shimmer{device[0] + 1}/emg_stream'))
        for device in candidates:
            port, mac, _, frame = device
            before = len(state['children'])
            try:
                if not monitor.node.count_publishers(f'/shimmer{port + 1}/emg_stream'):
                    info = run(['bluetoothctl', 'info', mac], check=False)
                    if 'Paired: yes' not in info:
                        continue
                    prepare([device])
                start_shimmer(port)
            except (RuntimeError, OSError, subprocess.SubprocessError) as error:
                skipped = state['children'][before:]
                stop_owned(skipped)
                for record in skipped:
                    record['stopped'] = True
                say(f'Preskačem {frame}: {error}')
            else:
                say(f'Odabran {frame} za snimanje i prikaz.')
                return port + 1
        raise RuntimeError('Nema dostupnog uparenog Shimmera. Uključite uređaj ili '
                           'odaberite njegov broj s --shimmers.')

    try:
        if not estimation_only:
            data_dir.mkdir(parents=True, exist_ok=True)
            if not os.access(data_dir, os.W_OK | os.X_OK):
                raise RuntimeError(f'Nema prava pisanja u {data_dir}.')
        if shimmers:
            prepare(devices)
        monitor = Monitor(devices, estimation_only)
        monitor.spin(2)  # Allow ROS graph discovery before checking for duplicates.
        if shimmers:
            for port, _, _, _ in devices:
                start_shimmer(port)
        else:
            selected = select_shimmer()
            shimmers = [selected]
            for port, _, _, _ in devices:
                if port + 1 != selected:
                    monitor.unwatch_shimmer(port + 1)
            state['shimmers'] = shimmers
            save_state(state)
        if not estimation_only:
            say('Dinamometar: ručku ostavite neopterećenom tijekom početnog nuliranja.')
            ensure_stream(FORCE_TOPIC, 'dinamometar',
                          ['ros2', 'launch', 'godirect_ros2', 'publish_grip_force.launch.py'])
        processed = [f'/shimmer{i}/emg_processed' for i in shimmers]
        endpoints = {'/record_grip', '/train_grip_model', '/load_grip_model'}
        existing = endpoints & dict(monitor.node.get_service_names_and_types()).keys()
        if existing or any(monitor.node.count_publishers(t)
                           for t in [*processed, ESTIMATED_FORCE_TOPIC]):
            raise RuntimeError('Obrada ili servisi već su pokrenuti u ovom ROS okruženju. '
                               'Zatvorite zasebni grip_services launch pa ponovite.')
        if estimation_only:
            endpoints = {'/load_grip_model'}
        services, log = spawn('grip_services', [
            'ros2', 'launch', 'shimmer_ros2', 'grip_services.launch.py',
            'shimmers:=' + ' '.join(f'shimmer{i}' for i in shimmers), f'data_dir:={data_dir}',
            f'emg_hz:={emg_hz}', f'estimation_only:={str(estimation_only).lower()}'])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            monitor.spin(0.1)
            visible = dict(monitor.node.get_service_names_and_types())
            if endpoints <= visible.keys() and all(monitor.ready(t) for t in processed):
                break
            if services.poll() is not None:
                break
        else:
            raise RuntimeError(f'Obrađeni tokovi ili servisi nisu spremni. Zapis: {log}')
        if services.poll() is not None:
            raise RuntimeError(f'Obrada i servisi su se ugasili. Zapis: {log}')
        if estimation_only:
            activate_model(monitor.ros, monitor.node, model_path)
            deadline = time.monotonic() + 5
            while not monitor.ready(ESTIMATED_FORCE_TOPIC):
                if time.monotonic() >= deadline or services.poll() is not None:
                    raise RuntimeError(f'Nema svježe procjene sile. Zapis: {log}')
                monitor.spin(0.1)
        if not no_gui:
            if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
                raise RuntimeError('Nema grafičke sesije za PlotJuggler. Koristite --no-gui.')
            layout = logs / 'plotjuggler.xml'
            make_layout(layout, shimmers, estimation_only)
            spawn('plotjuggler', ['ros2', 'run', 'plotjuggler', 'plotjuggler',
                                 '--layout', str(layout), '--start_streamer',
                                 '--window_title', 'EMG i sila stiska'])
            say('U PlotJuggler dijalogu potvrdite odabrane topice tipkom OK.')
        if estimation_only:
            say(f'SPREMNO. Procjena sile izlazi na {ESTIMATED_FORCE_TOPIC}.')
        else:
            say('SPREMNO. U drugom terminalu koristite ./pokreni.sh record, train ili estimate.')
            say(f'Podaci: {data_dir}.')
        say('Za kraj Ctrl+C ili ./pokreni.sh stop.')
        missing = set()
        while True:
            monitor.spin(0.5)
            for process in children:
                record = next(r for r in state['children'] if r['pid'] == process.pid)
                if (record.get('stopped') is not True and record['name'] != 'plotjuggler'
                        and process.poll() is not None):
                    raise RuntimeError(f'{record["name"]} se ugasio. Zapis: {record["log"]}')
            current = {t for t, (_, last, _) in monitor.samples.items() if time.monotonic() - last > 5}
            for topic in current - missing:
                say(f'PREKID PODATAKA: {topic}; provjerite uređaj i zapis čvora.')
            for topic in missing - current:
                say(f'PODACI PONOVNO STIŽU: {topic}')
            missing = current
    finally:
        say('Zatvaram procese pokrenute ovom skriptom…')
        stop_owned(state['children'])
        for process in children:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        if monitor:
            monitor.close()
        STATE.unlink(missing_ok=True)
        lock.close()
    return 0


def status(devices, estimation_only=False):
    monitor = Monitor(devices, estimation_only)
    try:
        monitor.spin(4)
        ready = True
        for topic in monitor.topics:
            ok = monitor.ready(topic)
            count = monitor.samples[topic][0]
            say(f'{"OK" if ok else "NEMA PODATAKA"}: {topic} ({count} novih poruka)')
            ready = ready and ok
        return 0 if ready else 1
    finally:
        monitor.close()


def resolve_recording(name, data_dir):
    """Turn a session label or the start of an ID into a recording ID.

    A full ID passes through: the service checks it against its own data directory.
    """
    if RECORDING_ID.fullmatch(name):
        return name
    import analiza  # The offline report next to this script.
    return analiza.grip_report.find_recording(data_dir, name)


def recording_mvc(recording_id, data_dir):
    if not RECORDING_ID.fullmatch(recording_id):
        raise ValueError('Za --mvc-from zadajte ID spremljene snimke.')
    path = data_dir / 'recordings' / recording_id / 'force.csv'
    with path.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        if 'force_n' not in (reader.fieldnames or []):
            raise ValueError(f'U {path} nedostaje stupac force_n.')
        peak = 0.0
        for row in reader:
            try:
                force = float(row['force_n'])
            except (ValueError, TypeError) as error:
                raise ValueError(f'Neispravna sila u {path}, redak {reader.line_num}.') from error
            if not math.isfinite(force):
                raise ValueError(f'Neispravna sila u {path}, redak {reader.line_num}.')
            peak = max(peak, force)
    if peak <= 0:
        raise ValueError(f'U {path} nema pozitivnog uzorka sile.')
    return peak


def call_service(ros, node, service, name, request, timeout):
    client = node.create_client(service, name)
    try:
        if not client.wait_for_service(timeout_sec=5):
            raise RuntimeError(f'{name} nije dostupan. Provjerite način rada pokretača.')
        future = client.call_async(request)
        ros.spin_until_future_complete(node, future, timeout_sec=timeout)
        if not future.done():
            raise RuntimeError(f'Isteklo je čekanje na {name}. Provjerite zapis pokretača.')
        response = future.result()
        if not response.success:
            raise RuntimeError(response.message)
        say(response.message)
        return response
    finally:
        node.destroy_client(client)


def activate_model(ros, node, path):
    from emg_grip_interfaces.srv import LoadGripModel

    return call_service(ros, node, LoadGripModel, '/load_grip_model',
                        LoadGripModel.Request(model_path=str(Path(path).expanduser().resolve())), 10)


def model_shimmers(model_path, emg_hz):
    model = json.loads(model_path.read_text(encoding='utf-8'))
    sensors = {f'/shimmer{port + 1}/emg_processed/ch1_mv': (port + 1, frame)
               for port, _, _, frame in DEVICES}
    try:
        if (model['version'], model['kind'], model['output']) != (2, 'ridge', 'grip_force_n'):
            raise ValueError('Za pokretanje je potreban model za prvi EMG kanal.')
        features = model['features']
        rates = model['emg_hz']
        if not features or len(set(features)) != len(features) or len(rates) != len(features):
            raise ValueError('Model nema valjanu konfiguraciju Shimmera.')
        selected = []
        for feature, rate in zip(features, rates):
            index, frame = sensors[feature]
            if model['frame_ids'][feature.rsplit('/', 1)[0]] != [frame]:
                raise ValueError(f'Izvor EMG-a u modelu ne odgovara uređaju {frame}.')
            if not math.isclose(float(rate), emg_hz, abs_tol=0.01):
                raise ValueError(f'Model očekuje {rate} Hz. Zadajte odgovarajući --emg-hz.')
            selected.append(index)
        return selected
    except (KeyError, TypeError) as error:
        raise ValueError('Model nema valjanu konfiguraciju poznatih Shimmera.') from error


def service_command(args):
    import rclpy
    from rclpy.node import Node
    from emg_grip_interfaces.msg import GripForce
    from emg_grip_interfaces.srv import RecordGrip, TrainGrip
    import analiza  # The offline report next to this script.

    rclpy.init(args=[])
    node = Node(f'lab_klijent_{os.getpid()}')

    try:
        if args.action == 'record':
            if not args.free:
                last_percent = None

                def cue(msg):
                    nonlocal last_percent
                    percent = round(100 * msg.grip_force / args.mvc)
                    if percent != last_percent:
                        say(f'Cilj: {percent}% ({msg.grip_force:g} N)')
                        last_percent = percent
                node.create_subscription(GripForce, '/grip_force_target', cue, 10)
                deadline = time.monotonic() + 5
                while not node.count_publishers('/grip_force_target'):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Nema ciljnog topica. Prvo pokrenite ./pokreni.sh.')
                    rclpy.spin_once(node, timeout_sec=0.1)
            request = RecordGrip.Request(session=args.values[0], duration_sec=args.duration,
                                         guided=not args.free, mvc_n=args.mvc or 0.0)
            say(f'Pokrećem snimanje ({args.duration:g} s).')
            response = call_service(rclpy, node, RecordGrip, '/record_grip', request, args.duration + 20)
            say(f'ID snimke: {response.recording_id}')
            say(f'{response.directory} ({response.aligned_rows} poravnatih redaka)')
            meta = json.loads((Path(response.directory) / 'metadata.json').read_text())
            for topic, stats in meta['streams'].items():
                say(f'{topic}: {stats["observed_hz"]:.1f} / {stats["expected_hz"]:.1f} Hz, '
                    f'{stats["samples"]} uzoraka, najveći razmak {stats["max_gap_ms"]:.1f} ms')
            say(f'Pokrivenost poravnanja: {meta["coverage_fraction"]:.1%}\n')
            # Show at once whether the grip followed the targets, while it can be repeated.
            analiza.check_recording(Path(response.directory).parents[1], response.recording_id)
        elif args.action == 'train':
            request = TrainGrip.Request(training_ids=args.values, validation_ids=args.validation)
            response = call_service(rclpy, node, TrainGrip, '/train_grip_model', request, 30)
            say(f'Model: {response.model_path}')
            if args.activate:
                activate_model(rclpy, node, response.model_path)
            # Error by force level on the model's own recordings, with a warning
            # when a recording holds too little grip for the error to mean much.
            say('')
            analiza.evaluate(Path(response.model_path).parents[1], response.model_path, [])
        else:
            activate_model(rclpy, node, args.values[0])
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
    return 0


def main():
    parser = argparse.ArgumentParser(description='Priprema i pokretanje EMG laboratorija jednom naredbom.')
    parser.add_argument('action', nargs='?', default='start',
                        choices=['start', 'prepare', 'status', 'stop', 'record', 'train', 'estimate',
                                 'self-test'])
    parser.add_argument('values', nargs='*', metavar='SESIJA|SNIMKA|MODEL',
                        help='Snimka se zadaje oznakom sesije ili ID-jem.')
    parser.add_argument('--no-gui', action='store_true', help='Pokreni senzore bez PlotJugglera.')
    parser.add_argument('--shimmers', type=int, nargs='+', choices=range(1, len(DEVICES) + 1),
                        help='Shimmeri za start/prepare/status. Start bez odabira koristi jedan dostupan uređaj.')
    parser.add_argument('--model', type=Path, metavar='JSON',
                        help='Pokreni samo EMG i procjenu s ovim modelom, bez dinamometra.')
    parser.add_argument('--data-dir', type=Path, default=DATA_DIR,
                        help='Mapa podataka: odredište za start; za record i train mjesto '
                             'u kojem se snimka traži po oznaci.')
    parser.add_argument('--emg-hz', type=float, default=512.0,
                        help='Frekvencija Shimmera za start (zadano 512 Hz).')
    parser.add_argument('--duration', type=float, default=30.0, help='Trajanje snimanja u sekundama.')
    mvc_group = parser.add_mutually_exclusive_group()
    mvc_group.add_argument('--mvc', type=float, help='Referentni maksimalni stisak u N.')
    mvc_group.add_argument('--mvc-from', metavar='SNIMKA',
                           help='Uzmi vršnu izmjerenu silu iz snimke maksimalnog stiska.')
    parser.add_argument('--free', action='store_true', help='Snimaj bez vođenih razina stiska.')
    parser.add_argument('--validation', nargs='+', default=[], metavar='SNIMKA',
                        help='Snimke za validaciju modela.')
    parser.add_argument('--activate', action='store_true', help='Aktiviraj model nakon treniranja.')
    args = parser.parse_intermixed_args()
    if args.model is not None and args.action != 'start':
        parser.error('--model vrijedi za pokretanje. Za učitavanje u aktivni čvor koristite estimate.')
    if args.action in ('record', 'estimate') and len(args.values) != 1:
        parser.error(f'{args.action} traži točno jedan argument.')
    if args.action == 'train' and not args.values:
        parser.error('train traži barem jednu snimku za učenje.')
    if args.values and args.action not in ('record', 'train', 'estimate'):
        parser.error(f'{args.action} ne prima pozicijske argumente.')
    if args.action == 'record':
        if not 20 <= args.duration <= 35:
            parser.error('Trajanje snimke mora biti između 20 i 35 s.')
        if not args.free and args.mvc is None and args.mvc_from is None:
            parser.error('Za vođeno snimanje zadajte --mvc-from SNIMKA ili pozitivni --mvc u N.')
        if args.mvc is not None and (not math.isfinite(args.mvc) or args.mvc <= 0):
            parser.error('--mvc mora biti pozitivan broj u N.')
    if args.shimmers and len(set(args.shimmers)) != len(args.shimmers):
        parser.error('Svaki Shimmer odaberite samo jednom.')
    if not 500 <= args.emg_hz <= 1024:
        parser.error('--emg-hz mora biti između 500 i 1024 Hz.')
    emg_hz = 32768 / round(32768 / int(args.emg_hz))
    STATE_DIR.mkdir(mode=0o700, exist_ok=True)
    # Handle TERM through the same cleanup as Ctrl+C.
    def interrupt(*_):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, interrupt)
    try:
        if args.action == 'self-test':
            return subprocess.call([sys.executable, str(ROOT / 'tests/smoke_grip.py'), str(emg_hz),
                                    *map(str, sorted(args.shimmers or [DEFAULT_SHIMMER]))])
        if args.action in ('record', 'train'):
            # Recordings are looked up where the running launcher stores them,
            # unless another directory was given.
            data_dir = Path(read_state().get('data_dir', DATA_DIR) if args.data_dir == DATA_DIR
                            else args.data_dir).expanduser()
            if args.action == 'train':
                args.values = [resolve_recording(name, data_dir) for name in args.values]
                args.validation = [resolve_recording(name, data_dir) for name in args.validation]
            elif args.mvc_from is not None:
                args.mvc = recording_mvc(resolve_recording(args.mvc_from, data_dir), data_dir)
                say(f'MVC iz snimke {args.mvc_from}: {args.mvc:g} N.')
        if args.action in ('record', 'train', 'estimate'):
            return service_command(args)
        selected = sorted(args.shimmers or [])
        if args.action == 'start':
            model_path = args.model.expanduser().resolve() if args.model is not None else None
            if model_path is not None:
                required = model_shimmers(model_path, emg_hz)
                if selected and selected != sorted(required):
                    raise ValueError(f'Model očekuje Shimmere {required}.')
                selected = required
            return start(args.no_gui, selected or None, args.data_dir.expanduser().resolve(),
                         emg_hz, model_path)
        state = read_state() if args.action == 'status' else {}
        selected = selected or state.get('shimmers') or [DEFAULT_SHIMMER]
        devices = [DEVICES[index - 1] for index in selected]
        if args.action == 'stop':
            stop()
        elif args.action == 'status':
            return status(devices, state.get('estimation_only', False))
        elif args.action == 'prepare':
            prepare(devices)
        return 0
    except KeyboardInterrupt:
        say('Zaustavljeno.')
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError, ImportError) as error:
        say(f'GREŠKA: {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
