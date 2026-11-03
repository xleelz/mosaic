import yaml, glob, os
D=os.path.dirname(__file__)
PART={'fixtures':[]}
# commands-registry rows for every modeled command (decision 6); filled in by build.py (needs all interfaces)
SEED_PROFILE={'redhat.vscode-yaml':{'id':'redhat.vscode-yaml','version':'1.14.0','source':'gallery','pinned':False,'is_builtin':False}}
GALLERY='https://marketplace.example/_apis/public/gallery'
SYNC='https://sync.example/v1'
PART['fixtures']=[
 {'id':'remote-server-seed','summary':'remote-server state: one user extension installed in the default profile, and the area\'s commands registered in the CommandsRegistry (decision 6).',
  'state':{'extensions-profile-scanner-service':{'profile_extensions':SEED_PROFILE},'commands-registry':{'commands':{}}}},
 {'id':'remote-server-marketplace','summary':'A product with a Marketplace (product.json extensionsGallery.serviceUrl set); the OSS product.json has none.','extends':['one-window-folder','remote-server-seed'],
  'config':{'product-extensions-gallery-service-url':GALLERY}},
 {'id':'remote-server-sync','summary':'A product with a settings sync store (product.json configurationSync.store set); the OSS product.json has none.','extends':['one-window-folder','remote-server-seed'],
  'config':{'product-configuration-sync-store-url':SYNC}},
 {'id':'remote-server-srv1','summary':'A remote folder: window w1 connects to the remote server instance srv1 (resolver result for ssh-remote+dev-box is seeded in remote-authority-resolver-service).','extends':['one-window-folder','remote-server-seed'],
  'topology':{'remote-server-process':['srv1']}},
]
