# Maintainer: Battle.net Launcher4Linux contributors
# Build a system-wide package:  makepkg -si
pkgname=battlenet-launcher4linux
pkgver=1.0.0
pkgrel=1
pkgdesc="Minimal Battle.net launcher for Linux (umu/Proton, no Lutris)"
arch=('any')
url="https://github.com/cr-analytic/d4-launcherT"
license=('MIT')
depends=('python' 'umu-launcher')
optdepends=(
    'python-gobject: graphical launcher'
    'libadwaita: graphical launcher'
    'gtk4: graphical launcher'
    'vulkan-tools: `bnl doctor` Vulkan check'
    'gamemode: optional gamemoderun wrapper'
    'mangohud: optional performance overlay'
)
source=()

package() {
    cd "$startdir"
    make PREFIX=/usr DESTDIR="$pkgdir" install
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
    install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
}
