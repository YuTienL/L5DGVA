/**
 * Abstract: 
 * Class dv_types includes types which are used by elements of the
 * dv test environment but which have no natural home.
 */

`ifndef GUARD_DV_TYPES_SV
`define GUARD_DV_TYPES_SV

/** Typedef used to simplify the passing around of queues of strings. */
typedef string dv_name_q[$];

class dv_types;

  /** Enumerated defining the different scoreboard ordering algorithms. */
  typedef enum { IN_ORDER, WITH_LOSSES, OUT_OF_ORDER } order_enum;

  /** 
   * Struct type used to encapsulate configuration information which is extracted from the
   * generated .cfg files.
   */
  typedef struct {
    string name;
    string value;
  } cfg_values_struct;

endclass: dv_types

`endif // GUARD_DV_TYPES_SV
