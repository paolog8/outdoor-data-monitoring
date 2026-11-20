-- Entity classes

COMMENT ON TABLE solar_cell IS 'A solar cell is [...]'


COMMENT ON COLUMN solar_cell.configuration IS 'Each solar cell may have a configuration, which is the kind of electrical configuration/coupling the solar cell/cells are arranged into (single cell, tandem, (1,2,3) terminals, module, mini-module)'

COMMENT ON COLUMNS substrate.geometry IS 'Each substrate must have a geometry, which is the pattern of laser scribes on the substrate'


-- SHOULD ADD ONLY CONFIRMED ASSERTIONS, NOT WORK IN PROGRESS
