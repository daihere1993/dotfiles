#!/usr/bin/env ruby

require 'tempfile'
require 'yaml'

profiles_path, merge_uid, rules_uid = ARGV
abort 'usage: bind-clash-verge-profiles.rb <profiles.yaml> <merge-uid> <rules-uid>' unless profiles_path && merge_uid && rules_uid

profiles = YAML.load_file(profiles_path)
abort "invalid Clash Verge profiles file: #{profiles_path}" unless profiles.is_a?(Hash)

items = profiles['items']
abort "invalid Clash Verge profiles file: #{profiles_path}" unless items.is_a?(Array)

updated = 0
items.each do |item|
  next unless item.is_a?(Hash) && item['type'] == 'remote'

  option = item['option'] ||= {}
  abort "invalid remote profile option in #{profiles_path}" unless option.is_a?(Hash)

  changed = option['merge'] != merge_uid || option['rules'] != rules_uid
  option['merge'] = merge_uid
  option['rules'] = rules_uid
  updated += 1 if changed
end

if updated.positive?
  mode = File.stat(profiles_path).mode & 0o777
  directory = File.dirname(profiles_path)
  temporary = Tempfile.new(['profiles', '.yaml'], directory)
  begin
    temporary.write(YAML.dump(profiles))
    temporary.flush
    temporary.fsync
    File.chmod(mode, temporary.path)
    temporary.close
    File.rename(temporary.path, profiles_path)
  ensure
    temporary.close unless temporary.closed?
    temporary.unlink if File.exist?(temporary.path)
  end
end

puts "Bound #{updated} Clash Verge remote profile(s) to merge=#{merge_uid}, rules=#{rules_uid}."
