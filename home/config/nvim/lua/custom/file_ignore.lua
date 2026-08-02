local M = {}

-- Manual ignore rules shared by Telescope and Neo-tree.
-- Edit only this table; both plugins consume derived formats below.
M.entries = {
  names = {
    '.git',
    'node_modules',
    '.DS_Store',
    'thumbs.db',
  },
  patterns = {
    -- '__pycache__',
    -- '*.pyc',
  },
}

local name_to_telescope_pattern = {
  ['.git'] = '%.git/',
  ['node_modules'] = 'node_modules/',
  ['.DS_Store'] = '%.DS_Store$',
  ['thumbs.db'] = 'thumbs%.db$',
}

---@return string[]
function M.telescope_patterns()
  local patterns = {}

  for _, name in ipairs(M.entries.names) do
    local pattern = name_to_telescope_pattern[name]
    if pattern then
      table.insert(patterns, pattern)
    else
      table.insert(patterns, vim.pesc(name))
    end
  end

  return patterns
end

function M.neo_tree_filtered_items()
  return {
    hide_dotfiles = false,
    hide_gitignored = true,
    hide_by_name = M.entries.names,
    hide_by_pattern = M.entries.patterns,
  }
end

return M
