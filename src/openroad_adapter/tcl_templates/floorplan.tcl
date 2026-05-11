## floorplan.tcl  — parameterized floorplan stage
## Variables injected by EDARunner via Jinja2

read_lef  {{ pdk_lef }}
{% for extra_lef in extra_lefs | default([]) %}
read_lef  {{ extra_lef }}
{% endfor %}
read_liberty {{ lib_file }}
read_verilog {{ work_dir }}/synthesis/synth.v
link_design  {{ design_name }}

read_sdc {{ work_dir }}/synthesis/synth.sdc

initialize_floorplan \
    -die_area  "0 0 {{ die_area_x }} {{ die_area_y }}" \
    -core_area "{{ core_margin }} {{ core_margin }} {{ die_area_x | float - core_margin | float }} {{ die_area_y | float - core_margin | float }}" \
    -site      {{ site_name }}

{% if macro_placement_file is defined %}
source {{ macro_placement_file }}
{% endif %}

place_pins \
    -hor_layers {{ hor_pin_layer | default("metal3") }} \
    -ver_layers {{ ver_pin_layer | default("metal2") }}

write_def   {{ work_dir }}/floorplan/floorplan.def
write_db    {{ work_dir }}/floorplan/floorplan.odb

report_design_area
puts "METRIC: core_area=[get_property [current_design] core_area]"
puts "METRIC: die_area=[get_property [current_design] die_area]"
