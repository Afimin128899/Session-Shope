#!/usr/bin/env python3
"""Install an independent two-minute monitor for the existing bot service."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from deploy.create_service import unit_quote
from deploy.setup_backups import save_unit, PREFIX


def units(project,python,service):
    header=PREFIX+'# Project: '+str(project)+'\n'
    return {'session-shope-monitor.service':header+f'''[Unit]
Description=Sband ACCS independent health monitor
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory={str(project).replace('%','%%')}
ExecStart={unit_quote(str(python))} -m deploy.healthcheck --project {unit_quote(str(project))} --service {unit_quote(service)}
TimeoutStartSec=3min
UMask=0077
''','session-shope-monitor.timer':header+'''[Unit]
Description=Sband ACCS check every two minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=2min
Unit=session-shope-monitor.service

[Install]
WantedBy=timers.target
'''}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--service',default='session-shope.service')
    args=parser.parse_args()
    if os.geteuid()!=0: raise ValueError('Запускайте через sudo.')
    from deploy.healthcheck import unit
    if unit(args.service).get('LoadState')!='loaded': raise ValueError('Сервис бота не найден.')
    project=args.project.resolve()
    for name,content in units(project,Path(sys.executable),args.service).items(): save_unit(Path('/etc/systemd/system')/name,content)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now','session-shope-monitor.timer'],check=True)
    print('Мониторинг настроен: каждые 2 минуты, напоминание об одной проблеме — раз в час.')


if __name__=='__main__':
    try: main()
    except (ValueError,OSError,subprocess.CalledProcessError): raise SystemExit('Не удалось настроить мониторинг. Проверьте сервис бота и права root.')
