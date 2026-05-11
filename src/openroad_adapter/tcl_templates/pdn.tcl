## pdn.tcl — power distribution network generation

read_lef  {{ pdk_lef }}
{% for extra_lef in extra_lefs | default([]) %}
read_lef  {{ extra_lef }}
{% endfor %}
read_liberty {{ lib_file }}
read_db {{ work_dir }}/floorplan/floorplan.odb
read_sdc {{ work_dir }}/synthesis/synth.sdc

add_global_connection -net VDD -pin_pattern {^VDD$}  -power
add_global_connection -net VSS -pin_pattern {^VSS$}  -ground

set_voltage_domain -name CORE -power VDD -ground VSS

define_pdn_grid \
    -name CORE_GRID \
    -voltage_domains CORE \
    -starts_with POWER

add_pdn_stripe \
    -followpins \
    -layer  {{ pdn_follow_layer | default("metal1") }} \
    -width  {{ pdn_rail_width   | default(0.48)      }}

add_pdn_stripe \
    -layer  {{ pdn_stripe_layer | default("metal5") }} \
    -width  {{ pdn_stripe_width | default(1.6)      }} \
    -pitch  {{ pdn_stripe_pitch | default(56.0)     }} \
    -offset {{ pdn_stripe_offset| default(2.0)      }}

add_pdn_connect \
    -layers "{{ pdn_follow_layer | default('metal1') }} {{ pdn_stripe_layer | default('metal5') }}"

pdngen

write_def  {{ work_dir }}/pdn/pdn.def
write_db   {{ work_dir }}/pdn/pdn.odb

puts "PDN generation complete."
