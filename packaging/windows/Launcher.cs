using System;
using System.IO;
using System.Diagnostics;
using System.Windows.Forms;
class ESA {
 [STAThread] static int Main(string[] args) {
  string root=AppDomain.CurrentDomain.BaseDirectory;
  string registry=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"ESA","workspaces.json");
  string selected=null;bool choose=false,create=false;
  for(int i=0;i<args.Length;i++) {if(args[i]=="--choose-workspace")choose=true;if(args[i]=="--registry"&&i+1<args.Length)registry=args[i+1];}
  if(choose || (args.Length==0 && !File.Exists(registry))) {
   var choice=MessageBox.Show("欢迎使用 ESA。\n\n继续已有工作区请选择‘是’；新建个人工作区请选择‘否’。\n已有工作区应包含 workspace.json 和 app.sqlite3。", "ESA · 选择工作区",MessageBoxButtons.YesNoCancel,MessageBoxIcon.Question);
   if(choice==DialogResult.Cancel)return 0;
   if(choice==DialogResult.Yes) {selected=ChooseFolder(false);if(selected==null)return 0;if(!File.Exists(Path.Combine(selected,"workspace.json"))||!File.Exists(Path.Combine(selected,"app.sqlite3"))){MessageBox.Show("这不是已有的ESA工作区。资料没有改变。", "ESA");return 1;}}
   else {selected=ChooseFolder(true);if(selected==null)return 0;create=true;}
  }
  try {
   for(int attempt=0;attempt<2;attempt++) {
   var info=new ProcessStartInfo(Path.Combine(root,"runtime","python.exe"));
   info.WorkingDirectory=root; info.UseShellExecute=false;info.CreateNoWindow=true;
   info.RedirectStandardError=true;info.RedirectStandardOutput=true;
   info.StandardErrorEncoding=System.Text.Encoding.UTF8;info.StandardOutputEncoding=System.Text.Encoding.UTF8;
   info.Arguments="-B -X utf8 -m app.launcher open";
   if(selected!=null)info.Arguments+=" --data-dir "+Quote(selected);
   if(create)info.Arguments+=" --create";
   for(int i=0;i<args.Length;i++){string arg=args[i];if(arg=="--choose-workspace")continue;if(selected!=null&&arg=="--data-dir"){i++;continue;}if(selected!=null&&arg=="--create")continue;info.Arguments+=" "+Quote(arg);}
   using(var process=Process.Start(info)) {string output=process.StandardOutput.ReadToEnd();string error=process.StandardError.ReadToEnd();process.WaitForExit();if(process.ExitCode==0)return 0;
    if(attempt==0&&error.Contains("WORKSPACE_MISSING")) {
     var choice=MessageBox.Show("上次登记的工作区已移动或不完整，未在旧位置创建空库。\n\n‘是’：定位原工作区；‘否’：明确新建；‘取消’：退出。", "ESA · 恢复工作区",MessageBoxButtons.YesNoCancel,MessageBoxIcon.Warning);
     if(choice==DialogResult.Cancel)return 0;
     create=choice==DialogResult.No;selected=ChooseFolder(create);if(selected==null)return 0;
     continue;
    }
    MessageBox.Show("启动没有完成。\n\n"+error,"ESA · 启动问题",MessageBoxButtons.OK,MessageBoxIcon.Warning);return process.ExitCode;}}
   return 0;
  } catch(Exception e) {MessageBox.Show("无法启动内置运行时，请完整解压发行目录。\n\n"+e.Message,"ESA");return 1;}
 }
 static string ChooseFolder(bool create) {
  // A simple native path input remains usable when the Shell picker is
  // unavailable (remote desktops, shell startup failures). Browse is optional.
  using(var form=new Form()) {
   form.Text=create?"ESA · 明确新建工作区":"ESA · 打开已有工作区";
   form.StartPosition=FormStartPosition.CenterScreen;form.ClientSize=new System.Drawing.Size(600,160);
   form.FormBorderStyle=FormBorderStyle.FixedDialog;form.MaximizeBox=false;form.MinimizeBox=false;
   var label=new Label();label.Text=create?"输入新的空目录完整路径；已有数据请取消并选择打开已有。":"输入原工作区完整路径（包含 workspace.json 和 app.sqlite3）。";label.SetBounds(16,14,568,35);
   var input=new TextBox();input.AccessibleName="工作区完整路径";input.SetBounds(16,52,472,28);
   if(create)input.Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"ESA","workspaces","default");
   var browse=new Button();browse.Text="浏览…";browse.SetBounds(498,50,84,28);browse.Click+=(s,e)=>{using(var dialog=new FolderBrowserDialog()){dialog.Description=label.Text;if(dialog.ShowDialog(form)==DialogResult.OK)input.Text=dialog.SelectedPath;}};
   var ok=new Button();ok.Text=create?"明确新建":"打开原工作区";ok.SetBounds(330,108,136,32);
   ok.Click+=(s,e)=>{if(string.IsNullOrWhiteSpace(input.Text)){MessageBox.Show(form,"请填写完整目录路径。","ESA");return;}try{input.Text=Path.GetFullPath(input.Text.Trim());form.DialogResult=DialogResult.OK;}catch(Exception error){MessageBox.Show(form,error.Message,"ESA");}};
   var cancel=new Button();cancel.Text="取消";cancel.SetBounds(478,108,104,32);cancel.DialogResult=DialogResult.Cancel;
   form.Controls.AddRange(new Control[]{label,input,browse,ok,cancel});form.AcceptButton=ok;form.CancelButton=cancel;form.Shown+=(s,e)=>input.Focus();
   return form.ShowDialog()==DialogResult.OK?input.Text:null;
  }
 }
 static string Quote(string value) {
  var result=new System.Text.StringBuilder(); result.Append('"'); int slashes=0;
  foreach(char c in value) {
   if(c=='\\') {slashes++;continue;}
   if(c=='"') {result.Append('\\',slashes*2+1);result.Append(c);}
   else {result.Append('\\',slashes);result.Append(c);}
   slashes=0;
  }
  result.Append('\\',slashes*2);result.Append('"');return result.ToString();
 }
}
