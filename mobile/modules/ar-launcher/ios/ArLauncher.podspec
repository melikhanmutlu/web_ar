require 'json'

package = JSON.parse(File.read(File.join(__dir__, '..', 'package.json')))

Pod::Spec.new do |s|
  s.name           = 'ArLauncher'
  s.version        = package['version']
  s.summary        = package['description']
  s.author         = 'ARVision'
  s.homepage       = 'https://webar.up.railway.app'
  s.license        = 'MIT'
  s.platforms      = { ios: '15.1' }
  s.source         = { git: '' }
  s.static_framework = true
  s.dependency 'ExpoModulesCore'
  s.source_files = '*.swift'
end
