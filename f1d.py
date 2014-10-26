from __future__ import division # No automatic floor division
from base import *
from scipy.sparse import dia_matrix, csr_matrix, spdiags
from scipy.sparse.linalg import spsolve

class F1D(Flexure):
  def initialize(self, filename):
    super(F1D, self).initialize(filename)
    if debug: print 'F1D initialized'

  def run(self):
    if self.method == 'FD':
      # Finite difference
      super(F1D, self).FD()
      self.method_func = self.FD
    elif self.method == 'FFT':
      # Fast Fourier transform
      super(F1D, self).FFT()
      self.method_func = self.FFT
    elif self.method == "SPA":
      # Superposition of analytical solutions
      super(F1D, self).SPA()
      self.method_func = self.SPA
    elif self.method == "SPA_NG":
      # Superposition of analytical solutions,
      # nonuniform points
      super(F1D, self).SPA_NG()
      self.method_func = self.SPA_NG
    else:
      print 'Error: method must be "FD", "FFT", or "SPA"'
      self.abort()

    if debug: print 'F1D run'
    self.method_func ()
    # self.plot() # in here temporarily

  def finalize(self):
    if debug: print 'F1D finalized'
    super(F1D, self).finalize()   
    
  ########################################
  ## FUNCTIONS FOR EACH SOLUTION METHOD ##
  ########################################
  
  def FD(self):
    #try:
    #  self.plotChoice
    #except:
    #  self.plotChoice = None
    if self.plotChoice:
      self.gridded_x()
    # Only generate coefficient matrix if it is not already provided
    try:
      self.coeff
    except:
      self.elasprep() # define dx4 and D within self
      self.coeff_matrix_creator() # And define self.coeff
    self.direct_fd_solve() # Get the deflection, "w"

  def FFT(self):
    if self.plotChoice:
      self.gridded_x()
    print "The fast Fourier transform solution method is not yet implemented."
    sys.exit()
    
  def SPA(self):
    self.gridded_x()
    self.spatialDomainVars()
    self.spatialDomainGridded()

  def SPA_NG(self):
    self.spatialDomainVars()
    self.spatialDomainNoGrid()

  
  ######################################
  ## FUNCTIONS TO SOLVE THE EQUATIONS ##
  ######################################


  ## UTILITY
  ############

  def gridded_x(self):
    self.nx = self.q0.shape[0]
    self.x = np.arange(0,self.dx*self.nx,self.dx)
    
  
  ## SPATIAL DOMAIN SUPERPOSITION OF ANALYTICAL SOLUTIONS
  #########################################################

  # SETUP

  def spatialDomainVars(self):
    self.D = self.E*self.Te**3/(12*(1-self.nu**2)) # Flexural rigidity
    self.alpha = (4*self.D/(self.drho*self.g))**.25 # 1D flexural parameter
    self.coeff = self.alpha**3/(8*self.D)

  # GRIDDED

  def spatialDomainGridded(self):
  
    self.w = np.zeros(self.nx) # Deflection array
    
    for i in range(self.nx):
      # Loop over locations that have loads, and sum
      if self.q0[i]:
        dist = abs(self.x[i]-self.x)
        # -= b/c pos load leads to neg (downward) deflection
        self.w -= self.q0[i] * self.coeff * self.dx * np.exp(-dist/self.alpha) * \
          (np.cos(dist/self.alpha) + np.sin(dist/self.alpha))
    # No need to return: w already belongs to "self"
    

  # NO GRID

  def spatialDomainNoGrid(self):
  
    # Reassign q0 for consistency
    #self.q0_with_locs = self.q0 # nah, will recombine later
    self.x = self.q0[:,0]
    self.q0 = self.q0[:,1]
    
    self.w = np.zeros(self.x.shape)
    print self.w.shape
    
    i=0 # counter
    for x0 in self.x:
      dist = abs(self.x-x0)
      self.w -= self.q0[i] * self.coeff * self.dx * np.exp(-dist/self.alpha) * \
        (np.cos(dist/self.alpha) + np.sin(dist/self.alpha))
      if i==10:
        print dist
        print self.q0
      i+=1 # counter

  ## FINITE DIFFERENCE
  ######################
  
  def elasprep(self):
    """
    dx4, D = elasprep(dx,Te,E=1E11,nu=0.25)
    
    Defines the variables (except for the subset flexural rigidity) that are
    needed to run "coeff_matrix_1d"
    """
    self.dx4 = self.dx**4
    self.D = self.E*self.Te**3/(12*(1-self.nu**2))

  def coeff_matrix_creator(self):
    """
    coeff = coeff_matrix(D,drho,dx4,nu,g)
    where D is the flexural rigidity, nu is Poisson's ratio, drho is the  
    density difference between the mantle and the material filling the 
    depression, g is gravitational acceleration at Earth's surface (approx. 
    9.8 m/s), and dx4 is based on the distance between grid cells (dx).
    
    All grid parameters except nu and g are generated by the function
    varprep2d, located inside this module
    
    D must be one cell larger than q0, the load array.
  
    1D pentadiagonal matrix to solve 1D flexure with variable elastic 
    thickness via a Thomas algorithm (assuming that scipy uses a Thomas 
    algorithm).
    """
    
    self.coeff_start_time = time.time()
    
    # Construct sparse array

    if self.BC_W != 'Mirror' or self.BC_E != 'Mirror':
      # This step is done post-padding if Mirror is the boundary condition
      self.build_diagonals()

    ##############################
    # SELECT BOUNDARY CONDITIONS #
    ##############################
    
    # Some links that helped me teach myself how to set up the boundary conditions
    # in the matrix for the flexure problem:
    # 
    # Good explanation of and examples of boundary conditions
    # https://en.wikipedia.org/wiki/Euler%E2%80%93Bernoulli_beam_theory#Boundary_considerations
    # 
    # Copy of Fornberg table:
    # https://en.wikipedia.org/wiki/Finite_difference_coefficient
    # 
    # Implementing b.c.'s:
    # http://scicomp.stackexchange.com/questions/5355/writing-the-poisson-equation-finite-difference-matrix-with-neumann-boundary-cond
    # http://scicomp.stackexchange.com/questions/7175/trouble-implementing-neumann-boundary-conditions-because-the-ghost-points-cannot
    
    print "Boundary condition, West:", self.BC_W, type(self.BC_W)
    print "Boundary condition, East:", self.BC_E, type(self.BC_E)

    if self.BC_W != 'Mirror' or self.BC_E != 'Mirror':
      # Define an approximate maximum flexural wavelength to obtain
      # required distances to pad the array    
      self.calc_max_flexural_wavelength()

    if self.BC_W == 'Mirror' or self.BC_E == 'Mirror':
      # Boundaries that require padding!
      self.BCs_that_need_padding()
    # Both Stewart and Dirichlet can be called from inside the boundary 
    # conditions that require padding, so the "elif" is for if padding 
    # cases are not used.
    if self.BC_E == 'Dirichlet' and self.BC_W == 'Dirichlet':
      # Stewart defaults to Dirichlet for the unpicked side, so only choose 
      # this if both sides are Dirichlet
      self.BC_Dirichlet()
    if self.BC_E == 'Sandbox' and self.BC_W == 'Sandbox':
      # Sandbox is my testing ground - only choose if both are sandbox
      self.BC_Sandbox()
    if self.BC_E == '0Moment0Shear' or self.BC_W == '0Moment0Shear':
      self.BC_0Moment0Shear()
    if self.BC_E == 'Neumann' or self.BC_W == 'Neumann':
      self.BC_Neumann()
    if self.BC_E == 'Symmetric' or self.BC_W == 'Symmetric':
      self.BC_Symmetric()

    #self.assemble_diagonals_with_boundary_conditions() # if separated into fcn

    # Roll to keep the proper coefficients at the proper places in the
    # arrays: Python will naturally just do vertical shifts instead of 
    # diagonal shifts, so this takes into account the horizontal compoent 
    # to ensure that boundary values are at the right place.
    self.l2_orig = self.l2.copy()
    self.l2 = np.roll(self.l2, -2)
    self.l1 = np.roll(self.l1, -1)
    self.r1 = np.roll(self.r1, 1)
    self.r2 = np.roll(self.r2, 2)
    # Then assemble these rows: this is where the periodic boundary condition 
    # can matter.
    if self.BC_E == 'Periodic' or self.BC_W == 'Periodic':
      self.BC_Periodic()
    # If not periodic, standard assembly (see BC_Periodic fcn for the assembly 
    # of that set of coefficient rows
    else:
      self.diags = np.vstack((self.l2,self.l1,self.c0,self.r1,self.r2))
      self.offsets = np.array([-2,-1,0,1,2])

    # Everybody now (including periodic b.c. cases)
    self.coeff_matrix = spdiags(self.diags, self.offsets, self.nx, self.nx, format='csr')

    self.coeff_creation_time = time.time() - self.coeff_start_time
    print 'Time to construct coefficient (operator) array [s]:', self.coeff_creation_time
  
  def build_diagonals(self):
    """
    Builds the diagonals for the coefficient array
    Pulled out because it has to be done at a different time if that array is 
    padded
    """
    if np.isscalar(self.Te):
      # Diagonals, from left to right, for all but the boundaries 
      self.l2 = 1 * self.D/self.dx4
      self.l1 = -4 * self.D/self.dx4
      self.c0 = 6 * self.D/self.dx4 + self.drho*self.g
      self.r1 = -4 * self.D/self.dx4
      self.r2 = 1 * self.D/self.dx4
      # Make them into arrays
      self.l2 *= np.ones(self.q0.shape)
      self.l1 *= np.ones(self.q0.shape)
      self.c0 *= np.ones(self.q0.shape)
      self.r1 *= np.ones(self.q0.shape)
      self.r2 *= np.ones(self.q0.shape)
    elif type(self.Te) == np.ndarray:
      # l2 corresponds to top value in solution vector, so to the left (-) side
      # Good reference for how to determine central difference (and other) coefficients is:
      # Fornberg, 1998: Generation of Finite Difference Formulas on Arbitrarily Spaced Grids
      Dm1 = self.D[:-2]
      D0  = self.D[1:-1]
      Dp1 = self.D[2:]
      self.l2 = ( Dm1/2. + D0 - Dp1/2. ) / self.dx4
      self.l1 = ( -6.*D0 + 2.*Dp1 ) / self.dx4
      self.c0 = ( -2.*Dm1 + 10.*D0 - 2.*Dp1 ) / self.dx4 + self.drho*self.g
      self.r1 = ( 2.*Dm1 - 6.*D0 ) / self.dx4
      self.r2 = ( -Dm1/2. + D0 + Dp1/2. ) / self.dx4
    # Number of columns; equals number of rows too - square coeff matrix
    self.ncolsx = self.c0.shape[0]
    
    # Either way, the way that Scipy stacks is not the same way that I calculate
    # the rows. It runs offsets down the column instead of across the row. So
    # to simulate this, I need to re-zero everything. To do so, I use 
    # numpy.roll. I should check out the other arrays to see that they work; 
    # perhaps this was a more serious problem than I knew.
    
    # Actually doing this after applying b.c.'s

  def BC_Periodic(self):
    """
    Periodic boundary conditions: wraparound to the other side.
    """
    if self.BC_E == 'Periodic' and self.BC_W == 'Periodic':
      # If both boundaries are periodic, we are good to go (and self-consistent)
      pass # It is just a shift in the coeff. matrix creation.
    else:
      # If only one boundary is periodic and the other doesn't implicitly 
      # involve a periodic boundary, this is illegal!
      # I could allow it, but would have to rewrite the Periodic b.c. case,
      # which I don't want to do to allow something that doesn't make 
      # physical sense... so if anyone wants to do this for some unforeseen 
      # reason, they can just split my function into two pieces themselves.
      sys.exit("Having the boundary opposite a periodic boundary condition\n"+
               "be fixed and not include an implicit periodic boundary\n"+
               "condition makes no physical sense.\n"+
               "Please fix the input boundary conditions. Aborting.")
    self.diags = np.vstack((self.r1,self.r2,self.l2,self.l1,self.c0,self.r1,self.r2,self.l2,self.l1))
    self.offsets = np.array([1-self.ncolsx,2-self.ncolsx,-2,-1,0,1,2,self.ncolsx-2,self.ncolsx-1])

  def BC_Dirichlet(self):
    """
    Boundary conditions stuck at 0!
    Nothing really has to be done: boundaries stuck at 0 anyway
    Haven't figured out how to move them... or if it is possible
    I have only seen bc motion on RHS with the explicit part of 
    implicit time-stepping matrix solutions
    """
    if self.BC_W == 'Dirichlet0_Neumann0':
      i=0
      self.l2[i] = np.nan # OFF GRID: using np.nan to throw a clear error if this is included
      self.l1[i] = np.nan # OFF GRID
      self.c0[i] = 0 * self.D/self.dx4 + self.drho*self.g
      self.r1[i] = -8 * self.D/self.dx4
      self.r2[i] = 2 * self.D/self.dx4
      i=1
      self.l2[i] = np.nan # OFF GRID
      self.l1[i] = -4 * self.D/self.dx4
      self.c0[i] = 0 * self.D/self.dx4 + self.drho*self.g
      self.r1[i] = -4 * self.D/self.dx4
      self.r2[i] = 2 * self.D/self.dx4
    if self.BC_E == 'Dirichlet0_Neumann0':
      # Coeffs no longer sum to 0 because, so w no longer free to be whatever 
      # it wants in absence of a local load, q
      i=-1
      self.r2[i] = np.nan # OFF GRID: using np.nan to throw a clear error if this is included
      self.r1[i] = np.nan # OFF GRID
      self.c0[i] = 0 * self.D/self.dx4 + self.drho*self.g
      self.l1[i] = -8 * self.D/self.dx4
      self.l2[i] = 2 * self.D/self.dx4
      i=-2
      self.r2[i] = np.nan # OFF GRID
      self.r1[i] = -4 * self.D/self.dx4
      self.c0[i] = 0 * self.D/self.dx4 + self.drho*self.g
      self.l1[i] = -4 * self.D/self.dx4
      self.l2[i] = 2 * self.D/self.dx4
    # If I do nothing to equations, displacements outside region are forced
    # to be 0, so pin solution to this
    if self.BC_W == 'Dirichlet': # Dirichlet0
      pass
    if self.BC_E == 'Dirichlet':
      pass

  def BC_Sandbox(self):
    """
    This is the sandbox for testing boundary conditions.
    It is the home of Andy Wickert's failed attempt to move Dirichlet boundary 
    conditions to non-zero values... he is now convinced that this either is 
    not possible for this kind of non-time-stepping problem that lacks an 
    explicit step or that it is beyond his insight (as of 8 March 2012)
    """
    print "WARNING! This is the sandbox set of boundary conditions. It is not\n\
          meant for actual computation, but rather for developing methods.\n\
          Works only for scalar Te."
    if np.isscalar(self.Te):
      """
      i=0
      self.l2[i] = np.nan # OFF GRID: using np.nan to throw a clear error if this is included
      self.l1[i] = np.nan # OFF GRID
      self.c0[i] = 10 * self.D/self.dx4 + self.drho*self.g
      self.r1[i] = -8 * self.D/self.dx4
      self.r2[i] = 2 * self.D/self.dx4
      self.q0[i] = self.q0[i] / (2*self.dx**5)
      i=1
      self.l2[i] = np.nan # OFF GRID
      self.l1[i] = -2 * self.D/self.dx4
      self.c0[i] = 6 * self.D/self.dx4 + self.drho*self.g
      self.r1[i] = -6 * self.D/self.dx4
      self.r2[i] = 2 * self.D/self.dx4
      self.q0[i] = self.q0[i] / (2*self.dx**3)
      """
      i=-1
      self.r2[i] = np.nan # OFF GRID: using np.nan to throw a clear error if this is included
      self.r1[i] = np.nan # OFF GRID
      self.c0[i] = 10 * self.D/self.dx4 + self.drho*self.g
      self.l1[i] = -8 * self.D/self.dx4
      self.l2[i] = 2 * self.D/self.dx4
      self.q0[i] = self.q0[i] / (2*self.dx**5)
      i=-2
      self.r2[i] = np.nan # OFF GRID
      self.r1[i] = -2 * self.D/self.dx4
      self.c0[i] = 6 * self.D/self.dx4 + self.drho*self.g
      self.l1[i] = -6 * self.D/self.dx4
      self.l2[i] = 2 * self.D/self.dx4
      self.q0[i] = self.q0[i] / (2*self.dx**3)

    else:
      sys.exit("Non-scalar Te; boundary conditions not valid... and these\n\
                sandbox experimental bc's are probably not valid for anything!")

  def BC_0Moment0Shear(self):
    """
    d2w/dx2 = d3w/dx3 = 0
    (no moment or shear)
    This simulates a free end (broken plate, end of a cantilevered beam: 
    think diving board tip)
    It is *not* yet set up to have loads placed on the ends themselves: 
    (look up how to do this, actually Wikipdia has some info)
    """
    # 0 moment and 0 shear
    if np.isscalar(self.Te):
    
      #self.q0[:] = np.max(self.q0)
    
      # SET BOUNDARY CONDITION ON WEST (LEFT) SIDE
      if self.BC_W == '0Moment0Shear':
        i=0
        """
        # This is for a Neumann b.c. combined with third deriv. = 0
        self.l2[i] = np.nan # OFF GRID: using np.nan to throw a clear error if this is included
        self.l1[i] = np.nan # OFF GRID
        self.c0[i] = 6 * self.D/self.dx4 + self.drho*self.g # this works but not sure how to get it.
                                                            # OH, you can w/ 0-flux boundary
                                                            # And 10 with 0-moment boundary
                                                            # But that doesn't make sense with pics.
                                                            # 0 moment should als be free deflec.
        self.r1[i] = -8 * self.D/self.dx4
        self.r2[i] = 2 * self.D/self.dx4
        """
        self.l2[i] = np.nan # OFF GRID: using np.nan to throw a clear error if this is included
        self.l1[i] = np.nan # OFF GRID
        self.c0[i] = 2 * self.D/self.dx4 + self.drho*self.g
        self.r1[i] = -4 * self.D/self.dx4
        self.r2[i] = 2 * self.D/self.dx4
        i=1
        self.l2[i] = np.nan # OFF GRID
        self.l1[i] = -2 * self.D/self.dx4
        self.c0[i] = 6 * self.D/self.dx4 + self.drho*self.g
        self.r1[i] = -6 * self.D/self.dx4
        self.r2[i] = 2 * self.D/self.dx4
        
      # SET BOUNDARY CONDITION ON EAST (RIGHT) SIDE
      if self.BC_E == '0Moment0Shear' or override:
        # Here, directly calculated new coefficients instead of just adding
        # them in like I did to save some time (for me) in the variable Te
        # case, below.
        i=-1
        self.r2[i] = np.nan # OFF GRID: using np.nan to throw a clear error if this is included
        self.r1[i] = np.nan # OFF GRID
        self.c0[i] = 6 * self.D/self.dx4 + self.drho*self.g
        self.l1[i] = -8 * self.D/self.dx4
        self.l2[i] = 2 * self.D/self.dx4
        i=-2
        self.r2[i] = np.nan # OFF GRID
        self.r1[i] = -4 * self.D/self.dx4
        self.c0[i] = 6 * self.D/self.dx4 + self.drho*self.g
        self.l1[i] = -4 * self.D/self.dx4
        self.l2[i] = 2 * self.D/self.dx4
        """
        self.r2[i] = np.nan # OFF GRID
        self.r1[i] = -4 * self.D/self.dx4
        self.c0[i] = 6 * self.D/self.dx4 + self.drho*self.g
        self.l1[i] = -4 * self.D/self.dx4
        self.l2[i] = 2 * self.D/self.dx4
        """
    else:
      # Variable Te
      # But this is really the more general solution, so we don't need the 
      # constant Te case... but I just keep it because I already wrote it
      # and it probably calculates the solution negligibly faster.
      # 
      # First, just define coefficients for each of the positions in the array
      # These will be added in code instead of being directly combined by 
      # the programmer (as I did above for constant Te), which might add 
      # rather negligibly to the compute time but save a bunch of possibility 
      # for unfortunate typos!

      # Also using 0-curvature boundary condition for D (i.e. Te)
      if self.BC_W == '0Moment0Shear':
        i=0
        self.BC_Te(i, '0 curvature') # Define coeffs
        self.l2[i] = np.nan
        self.l1[i] = np.nan
        self.c0[i] = self.c0_coeff_i + 4*self.l2_coeff_i + 2*self.l1_coeff_i
        self.r1[i] = self.r1_coeff_i - 4*self.l2_coeff_i - self.l1_coeff_i
        self.r2[i] = self.r2_coeff_i + self.l2_coeff_i
        i=1
        self.BC_Te(i, '0 curvature') # Define coeffs
        self.l2[i] = np.nan
        self.l1[i] = self.l1_coeff_i + 2*self.l2_coeff_i
        self.c0[i] = self.c0_coeff_i
        self.r1[i] = self.r1_coeff_i - 2*self.l2_coeff_i
        self.r2[i] = self.r2_coeff_i + self.l2_coeff_i
      
      if self.BC_E == '0Moment0Shear':
        i=-2
        self.BC_Te(i, '0 curvature') # Define coeffs
        self.l2[i] = self.l2_coeff_i + self.r2_coeff_i
        self.l1[i] = self.l1_coeff_i - 2*self.r2_coeff_i
        self.c0[i] = self.c0_coeff_i
        self.r1[i] = self.r1_coeff_i + 2*self.r2_coeff_i
        self.r2[i] = np.nan
        i=-1
        self.BC_Te(i, '0 curvature') # Define coeffs
        self.l2[i] = self.l2_coeff_i + self.r2_coeff_i
        self.l1[i] = self.l1_coeff_i - 4*self.r2_coeff_i - self.r1_coeff_i
        self.c0[i] = self.c0_coeff_i + 4*self.r2_coeff_i + 2*self.r1_coeff_i
        self.r1[i] = np.nan
        self.r2[i] = np.nan

  def BC_Neumann(self, override=False):
    """
    Constant gradient boundary condition
    Right now, constant gradient = 0, so Neumann0 would be good description
    And because I reach farther to cells beyond these, it is also 0-curvature
    """
    i=0
    self.l2[i] = np.nan # OFF GRID: using np.nan to throw a clear error if this is included
    self.l1[i] = np.nan # OFF GRID
    self.c0[i] = 6 * self.D/self.dx4 + self.drho*self.g
    self.r1[i] = -8 * self.D/self.dx4
    self.r2[i] = 2 * self.D/self.dx4
    i=1
    self.l2[i] = np.nan # OFF GRID
    self.l1[i] = -4 * self.D/self.dx4
    self.c0[i] = 6 * self.D/self.dx4 + self.drho*self.g
    self.r1[i] = -4 * self.D/self.dx4
    self.r2[i] = 2 * self.D/self.dx4
    i=-1
    self.r2[i] = np.nan # OFF GRID: using np.nan to throw a clear error if this is included
    self.r1[i] = np.nan # OFF GRID
    self.c0[i] = 6 * self.D/self.dx4 + self.drho*self.g
    self.l1[i] = -8 * self.D/self.dx4
    self.l2[i] = 2 * self.D/self.dx4
    i=-2
    self.r2[i] = np.nan # OFF GRID
    self.r1[i] = -4 * self.D/self.dx4
    self.c0[i] = 6 * self.D/self.dx4 + self.drho*self.g
    self.l1[i] = -4 * self.D/self.dx4
    self.l2[i] = 2 * self.D/self.dx4

  def BCs_that_need_padding(self):
    """
    This function acts as a main interface for BC_Mirror.
    
    It is needed because these functions pad the array, and if one pads it on 
    one side and the other pads it on the other, the final array isn't known 
    until both boundary conditions are evaluated. Because these padding 
    boundary conditions are evaluated outside of the static boundary b.c.'s, 
    it is necessary to have them combined here (instead of above)
    """

    # self.q0 not touched until later; the two functions called from this 
    # one modify self.q0pad
    self.q0pad = self.q0.copy() # Prep for concatenation

    #from matplotlib.pyplot import plot, show, figure
    #figure(2), plot(self.q0pad)

    # Build the proper boundary conditions
    if self.BC_W == 'Mirror' or self.BC_E == 'Mirror':
      print "MIRROR!"
      self.BC_Mirror()
    # Pad Te, if it is an array, to match q0
    self.pad_Te()

    #figure(1), plot(self.q0pad)
    #show()

    # Finally, we build the diagonal matrix and set its boundary conditions
    self.padded_edges_BCs()

  def BC_Mirror(self):
    """
    Mirrors q0 across the boundary on either the west (left) or east (right) 
    side, depending on the selections.
    
    This can, for example, produce a scenario in which you are observing 
    a mountain range up to the range crest (or, more correctly, the halfway 
    point across the mountain range).
    
    The mirror is run out to one flexural wavelength away from the main 
    part of the grid, after which it is clipped (if longer) or padded with 
    additional zeros (if not).
    
    This has similar rules to the no outside loads condition: if both sides 
    are mirrored, one will be mirrored and a periodic boundary condition will 
    be applied.
    """

    # Before starting, make sure that other side isn't "periodic": in that 
    # case, change it to Mirror because the solution is OFTEN the same and 
    # changing it should improve flow control (right-side padding desired 
    # in this case even if the right boundary was periodic)
    # Often but not always b/c if the domain is too short, it won't see its 
    # loads more than once with mirror, which goes against periodic (i.e. 
    # my numerical mirror doesn't work recursively like a real one would)
    if self.BC_E == 'Periodic' or self.BC_W == 'Periodic':
      print "Setting one periodic boundary in conjunction with one Mirror"
      print "boundary is OFTEN but not ALWAYS the same as setting both sides"
      print "to have no outside loads; this is because a periodic boundary"
      print "condition is often used to halve the distance that needs to be"
      print "padded."
      print "DEFAULTING TO BOTH MIRROR BOUNDARIES IN THIS SITUATION!"
      # One is already Mirror, so change both to make sure that we 
      # get both of them
      self.BC_E = 'Mirror'
      self.BC_W = 'Mirror'
    
    # First, see how far to pad: 1 flexural wavelength
    # Now this is done outside this function
    self.calc_max_flexural_wavelength()
    
    # Second, create the mirrored load grid
    self.q0_mirror = self.q0[::-1]
    #from matplotlib.pyplot import plot, figure
    #figure(4), plot(self.q0_mirror)
    
    # Third, make padding array (if needed)
    # If doing both sides, just repeat whole grid (if > flexural wavelength 
    # and more efficient than just repeating part of it on both sides)
    if len(self.q0_mirror) < self.maxFlexuralWavelength_ncells:
      zeropad = np.zeros(self.maxFlexuralWavelength_ncells - len(self.q0_mirror))

    # and self.BC_E = 'Mirror' or self.BC_W = 'Mirror':

    # Fourth, find what may need to be added to each side
    if self.BC_E == 'Mirror':
      if len(self.q0_mirror) < self.maxFlexuralWavelength_ncells:
        self.q0_mirror_E = np.concatenate((self.q0_mirror,zeropad))
      elif len(self.q0_mirror) >= self.maxFlexuralWavelength_ncells:
        self.q0_mirror_E = self.q0_mirror[:self.maxFlexuralWavelength_ncells]
    if self.BC_W == 'Mirror':
      if len(self.q0_mirror) < self.maxFlexuralWavelength_ncells:
        self.q0_mirror_W = np.concatenate((zeropad,self.q0_mirror))
      elif len(self.q0_mirror) > self.maxFlexuralWavelength_ncells:
        self.q0_mirror_W = self.q0_mirror[-self.maxFlexuralWavelength_ncells:]

    # Fifth, add things properly to each side
    # Starting with both sides being mirror bc's
    if self.BC_E == 'Mirror' and self.BC_W == 'Mirror':
      # Case 1: glom onto both sides because it is too short or too long
      if len(self.q0_mirror) < self.maxFlexuralWavelength_ncells \
        or len(self.q0_mirror) > 2*self.maxFlexuralWavelength_ncells:
        self.q0pad = np.concatenate((self.q0_mirror_W,self.q0pad,self.q0_mirror_E))
      # Case 2: Add to one side and later use a periodic boundary condition  
      # because it is just right and these are more efficient
      else:
        self.q0pad = np.concatenate((self.q0pad,self.q0_mirror))        
    # And then if just one side or the other is mirror:
    elif self.BC_E == 'Mirror':
      self.q0pad = np.concatenate((self.q0pad,self.q0_mirror_E))
    elif self.BC_W == 'Mirror':
      self.q0pad = np.concatenate((self.q0_mirror_W,self.q0pad))

  def BC_Symmetric(self):
    """
    "Mirror", but elegantly.
    """
    if self.BC_W == 'Symmetric':
      i=0
      self.BC_Te(i, 'symmetric') # Define coeffs
      self.l2[i] = np.nan
      self.l1[i] = np.nan
      self.c0[i] = self.c0_coeff_i
      self.r1[i] = self.r1_coeff_i + self.l1_coeff_i
      self.r2[i] = self.r2_coeff_i + self.l2_coeff_i
      i=1
      self.BC_Te(i, 'symmetric') # Define coeffs
      self.l2[i] = np.nan
      self.l1[i] = self.l1_coeff_i
      self.c0[i] = self.c0_coeff_i + self.l2_coeff_i
      self.r1[i] = self.r1_coeff_i
      self.r2[i] = self.r2_coeff_i
    
    if self.BC_E == 'Symmetric':
      i=-2
      self.BC_Te(i, 'symmetric') # Define coeffs
      self.l2[i] = self.l2_coeff_i
      self.l1[i] = self.l1_coeff_i
      self.c0[i] = self.c0_coeff_i + self.r2_coeff_i
      self.r1[i] = self.r1_coeff_i
      self.r2[i] = np.nan
      i=-1
      self.BC_Te(i, 'symmetric') # Define coeffs
      self.l2[i] = self.l2_coeff_i + self.r2_coeff_i
      self.l1[i] = self.l1_coeff_i + self.r1_coeff_i
      self.c0[i] = self.c0_coeff_i
      self.r1[i] = np.nan
      self.r2[i] = np.nan
    
  def calc_max_flexural_wavelength(self):
    """
    Returns the approximate maximum flexural wavelength
    This is important when padding of the grid is required: in Flexure (this 
    code), grids are padded out to one maximum flexural wavelength, but in any 
    case, the flexural wavelength is a good characteristic distance for any 
    truncation limit
    """
    if np.isscalar(self.D):
      Dmax = self.D
    else:
      Dmax = self.D.max()
    # This is an approximation if there is fill that evolves with iterations 
    # (e.g., water), but should be good enough that this won't do much to it
    alpha = (4*Dmax/(self.drho*self.g))**.25 # 2D flexural parameter
    self.maxFlexuralWavelength = 2*np.pi*alpha
    self.maxFlexuralWavelength_ncells = int(np.ceil(self.maxFlexuralWavelength / self.dx))
    
  def pad_Te(self):
    """
    Pad elastic thickness to match padded q0 array.
    This is needed for the Mirror boundary condition
    
    Mirror boundary conditions mirror the elastic thickness array out to the 
    desired distance.

    This function will do nothing if elastic thickness is a scalar... because 
    then it is not a grid that needs to be padded. It will also do nothing if 
    the boundary conditions do not include a "Mirror".

    Use linspace to keep value constant on both sides of the padding seam
    And also update D based on the extended Te array
    """

    if type(self.Te) == np.ndarray:
      self.Te_orig = self.Te.copy() # Save original Te
      if self.BC_W == 'Mirror' and self.BC_E == 'Mirror':
        # Case 1: padded on both sides 
        if len(self.Te_orig) < self.maxFlexuralWavelength_ncells:
          extrapad = np.ones( self.maxFlexuralWavelength_ncells - len(self.Te_orig) )
          padTeW = np.concatenate(( self.Te_orig[::-1][-1] * extrapad, self.Te_orig[::-1] ))
          padTeE = np.concatenate(( self.Te_orig[::-1], self.Te_orig[::-1][-1] * extrapad ))
          self.Te = np.concatenate((padTeW, self.Te,padTeE))
        elif len(self.Te_orig) > 2*self.maxFlexuralWavelength_ncells:
          padTeW = self.Te_orig[::-1][-self.maxFlexuralWavelength_ncells:]
          padTeE = self.Te_orig[::-1][:self.maxFlexuralWavelength_ncells]
          self.Te = np.concatenate((padTeW, self.Te, padTeE))
        # Case 2: Padded on right
        else:
          # Can't go the whole length because Te_orig is padded
          # SO THIS IS DIFFERENT FROM THE Q0, TE MIRRORING OF THE ENDPOINT 
          # BEFORE!
          padTeE = self.Te_orig[::-1][1:-1]
          self.Te = np.concatenate((self.Te,padTeE))
      # Combo and mirror-only cases already accounted for, so can just do a 
      # simple if
      elif self.BC_W == 'Mirror':
        if len(self.Te_orig) < self.maxFlexuralWavelength_ncells:
          extrapad = np.ones( self.maxFlexuralWavelength_ncells - len(self.Te_orig) )
          padTeW = np.concatenate(( self.Te_orig[::-1][-1] * extrapad, self.Te_orig[::-1] ))
        else:
          padTeW = self.Te_orig[::-1][-self.maxFlexuralWavelength_ncells:]
        self.Te = np.concatenate((padTeW,self.Te))
      elif self.BC_E == 'Mirror':
        if len(self.Te_orig) < self.maxFlexuralWavelength_ncells:
          extrapad = np.ones( self.maxFlexuralWavelength_ncells - len(self.Te_orig) )
          padTeE = np.concatenate(( self.Te_orig[::-1], self.Te_orig[::-1][-1] * extrapad ))
        else:
          padTeE = self.Te_orig[::-1][:self.maxFlexuralWavelength_ncells]
        self.Te = np.concatenate((self.Te,padTeE))
      # Update D
      self.D = self.E*self.Te**3/(12*(1-self.nu**2)) # Flexural rigidity
  
  def padded_edges_BCs(self):
    """
    Sets the boundary conditions outside of padded edges; this is important 
    for Mirror boundary conditions

    Also makes an archival copy of q0 for while q0 is temporarily replaced 
    by the padded version of it
    """

    # Then copy over q0
    self.q0 = self.q0pad.copy()
        
    # First, we have to build the diagonal matrix, which wasn't pre-done 
    # for us because we've just changed its size.
    self.build_diagonals()

    # Now we are all ready to throw this in the periodic boundary condition
    # matrix builder, if needed!
    if self.BC_E == 'Mirror' and self.BC_W == 'Mirror':
      # Case 1: glommed onto both sides because it is too short or too long
      # (Should have this be a maxFlexuralWavelength class variable, but
      # just recalculating for now)
      if len(self.q0_mirror) < self.maxFlexuralWavelength_ncells \
        or len(self.q0_mirror) > 2*self.maxFlexuralWavelength_ncells:
        if np.isscalar(self.Te):
          # Implemented only for constant Te, but produces less of a 
          # boundary effect on the solution
          self.BC_Stewart1(override = True)
        else:
          self.BC_Dirichlet()
      # Case 2: Adedd to one side and now use a periodic boundary condition 
      # because the array length is just right and these are more efficient
      else:
        self.BC_Periodic()
    else:
      # Apply other BC to both sides: one is padded so it won't matter, and 
      # the other one is where it counts
      if self.BC_E == 'Stewart1' or self.BC_W == 'Stewart1':
        self.BC_Stewart1(override = True)
      elif self.BC_E == 'Dirichlet' or self.BC_W == 'Dirichlet':
        # Would be better to use Stewart1 on padded side if possible, but not 
        # going to becasue it is implemented only for the constant Te case
        self.BC_Dirichlet()
      else: sys.exit("If only one side is padded and the other isn't, valid boundary\n"+
                     "condition options are 'Stewart1' and 'Dirichlet'. Aborting.")

  def BC_Te(self, i, case):
    """
    Utility function to help implement:
    0-curvature boundary condition for D (i.e. Te)
    D[i-1] = 2*D[i] - D[i+1]
    So this means constant gradient set by local Te distribution
    """
    
    if case == "0 curvature":
      if i == 0:
        D0  = self.D[1:-1][i] # = D[1]
        Dp1 = self.D[2:][i] # = D[2]
        Dm1 = 2*D0 - Dp1 # BC applied here
      elif i == -1:
        Dm1 = self.D[:-2][i]
        D0  = self.D[1:-1][i]
        Dp1 = 2*D0 - Dm1 # BC applied here
      else:
        # Away from boundaries and all is normal
        Dm1 = self.D[:-2][i]
        D0  = self.D[1:-1][i]
        Dp1 = self.D[2:][i]
        
    elif case == "symmetric":
      if i == 0:
        D0  = self.D[1:-1][i] # = D[1]
        Dp1 = self.D[2:][i] # = D[2]
        Dm1 = self.D[2:][i] # BC applied here
      elif i == -1:
        Dm1 = self.D[:-2][i]
        D0  = self.D[1:-1][i]
        Dp1 = self.D[:-2][i] # BC applied here
      else:
        # Away from boundaries and all is normal
        Dm1 = self.D[:-2][i]
        D0  = self.D[1:-1][i]
        Dp1 = self.D[2:][i]
    else:
      sys.exit("Invalid Te B.C. case")
    
    self.l2_coeff_i = ( Dm1/2. + D0 - Dp1/2. ) / self.dx4
    self.l1_coeff_i = ( -6.*D0 + 2.*Dp1 ) / self.dx4
    self.c0_coeff_i = ( -2.*Dm1 + 10.*D0 - 2.*Dp1 ) / self.dx4 + self.drho*self.g
    self.r1_coeff_i = ( 2.*Dm1 - 6.*D0 ) / self.dx4
    self.r2_coeff_i = ( -Dm1/2. + D0 + Dp1/2. ) / self.dx4
    
    """
    # Template
    self.l2[i] = self.l2_coeff_i
    self.l1[i] = self.l1_coeff_i
    self.c0[i] = self.c0_coeff_i
    self.r1[i] = self.r1_coeff_i
    self.r2[i] = self.r2_coeff_i
    """
      
  def direct_fd_solve(self):
    """
    w = direct_fd_solve()
      where coeff is the sparse coefficient matrix output from function
      coeff_matrix and q0 is the array of loads

    Sparse solver for one-dimensional flexure of an elastic plate
    """
    
    #print 'q0', self.q0.shape
    #print 'Te', self.Te.shape
    print 'maxFlexuralWavelength_ncells', self.maxFlexuralWavelength_ncells
    
    self.solver_start_time = time.time()
    
    self.q0sparse = csr_matrix(-self.q0) # Negative so bending down with positive load,
                                    # bending up with negative load (i.e. material
                                    # removed)
                                    # *self.dx
    # UMFpack is now the default, but setting true just to be sure in case
    # anything changes
    self.w = spsolve(self.coeff_matrix, self.q0sparse, use_umfpack=True)
    
    self.time_to_solve = time.time() - self.solver_start_time
    print 'Time to solve [s]:', self.time_to_solve
    
    # If needed, revert q0 and Te to original dimensions
    self.back_to_original_q0_Te_w()
    
    #print self.w.shape
    
    #print self.w
    
  def back_to_original_q0_Te_w(self):
    """
    Pull out the parts of q0, Te that we want for the padded "Mirror" boundary 
    condition case
    """
    # Clipping needed for the Mirror boundary condition.
    if self.BC_W == 'Mirror' or self.BC_E == 'Mirror':
      self.q0 = self.q0_orig
      if type(self.Te) == np.ndarray:
        self.Te = self.Te_orig
      if self.BC_E == 'Mirror' and self.BC_W == 'Mirror':
        # Case 1: padded on both sides 
        if len(self.q0_mirror) < self.maxFlexuralWavelength_ncells \
          or len(self.q0_mirror) > 2*self.maxFlexuralWavelength_ncells:
          print self.w.shape
          self.w = self.w[self.maxFlexuralWavelength_ncells:-self.maxFlexuralWavelength_ncells]
        # Case 2: Padded on right
        else:
          self.w = self.w[:len(self.q0_orig)]
      # Combo and mirror-only cases already accounted for, so can just do a 
      # simple if
      elif self.BC_W == 'Mirror':
        self.w = self.w[self.maxFlexuralWavelength_ncells:]
      elif self.BC_E == 'Mirror':
        self.w = self.w[:-self.maxFlexuralWavelength_ncells]

