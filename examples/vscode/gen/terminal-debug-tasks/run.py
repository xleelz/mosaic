import sys, os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import base, terminal, terminal_flows, debug, tasks, testing, output, commands, contribs, flows2, scen2, reconcile, extra, fixround
for m in sys.argv[1:]: __import__(m)
base.emit(os.path.join(base.VSC,'fragments','terminal-debug-tasks.yaml'))
print('components',len(base.COMPS),'interfaces',len(base.IFACES),'flows',len(base.FLOWS),'scenarios',len(base.SCEN))
